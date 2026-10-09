"""Local REST source for the product master.

Run with::

    uvicorn data.generator.product_api:app --port 8099

Exposes the two endpoints consumed by ``LoadProductsRest.dtsx``:

* ``GET /products?page=N``          - paged product master (base snapshot)
* ``GET /products/changes?since=``  - ~120 price/category deltas (SCD Type 2)

The same data is materialised on disk by :mod:`gen_sources` so CI can run the
package without starting this server.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Query

try:  # imported as a package (uvicorn data.generator.product_api:app)
    from .gen_sources import (
        LANDING,
        N_PRODUCT_CHANGES,
        PRODUCT_PAGE_SIZE,
        START_DATE,
        build_product_changes,
        build_products,
        business_days,
    )
except ImportError:  # run directly as a script
    from gen_sources import (  # type: ignore[no-redef]
        LANDING,
        N_PRODUCT_CHANGES,
        PRODUCT_PAGE_SIZE,
        START_DATE,
        build_product_changes,
        build_products,
        business_days,
    )

app = FastAPI(title="RetailMart Product API", version="1.0.0")

_rng = random.Random(20240101)
_products = build_products(random.Random(43))
_days = business_days(START_DATE, 90)
_changes = build_product_changes(_rng, _products, _days)
_CHANGES_BY_DAY = {c["change_date"]: c for c in _changes}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/products")
def products(page: int = Query(1, ge=1)) -> dict:
    start = (page - 1) * PRODUCT_PAGE_SIZE
    items = _products[start : start + PRODUCT_PAGE_SIZE]
    return {
        "page": page,
        "page_size": PRODUCT_PAGE_SIZE,
        "total": len(_products),
        "items": items,
    }


@app.get("/products/changes")
def product_changes(since: str = Query(START_DATE.isoformat())) -> dict:
    since_date = date.fromisoformat(since)
    items = [
        c for c in _changes if date.fromisoformat(c["change_date"]) >= since_date
    ]
    return {"since": since, "total": len(items), "changes": items}


def _emit_snapshots(landing: Path = LANDING) -> None:
    """Write the on-disk snapshots used when the API is not running."""
    landing.mkdir(parents=True, exist_ok=True)
    for page_number, start in enumerate(
        range(0, len(_products), PRODUCT_PAGE_SIZE), start=1
    ):
        payload = {
            "page": page_number,
            "page_size": PRODUCT_PAGE_SIZE,
            "total": len(_products),
            "items": _products[start : start + PRODUCT_PAGE_SIZE],
        }
        (landing / f"products_page_{page_number:03d}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    (landing / "product_changes.json").write_text(
        json.dumps({"changes": _changes}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    _emit_snapshots()
    print(
        f"emitted {len(_products)} products and {len(_changes)} changes "
        f"({N_PRODUCT_CHANGES} configured) to {LANDING}"
    )
