"""Local REST source for the product master.

Run with::

    uvicorn data.generator.product_api:app --port 8099

Exposes the two endpoints consumed by ``LoadProductsRest.dtsx``:

* ``GET /products?page=N``          - paged product master (base snapshot)
* ``GET /products/changes?since=``  - price/category deltas (SCD Type 2)

The endpoints serve exactly the same rows that ``gen_sources`` writes to disk,
so a package load and an API load produce identical SCD Type 2 versions.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Query

try:  # imported as a package (uvicorn data.generator.product_api:app)
    from .gen_sources import LANDING, PRODUCT_PAGE_SIZE, START_DATE, generate
except ImportError:  # run directly as a script
    from gen_sources import (  # type: ignore[no-redef]
        LANDING,
        PRODUCT_PAGE_SIZE,
        START_DATE,
        generate,
    )

app = FastAPI(title="RetailMart Product API", version="1.0.0")


@lru_cache(maxsize=1)
def _load() -> tuple[list[dict], list[dict]]:
    if not list(Path(LANDING).glob("products_page_*.json")):
        generate(Path(LANDING))
    products: list[dict] = []
    for path in sorted(Path(LANDING).glob("products_page_*.json")):
        products.extend(json.loads(path.read_text(encoding="utf-8"))["items"])
    changes = json.loads(
        (Path(LANDING) / "product_changes.json").read_text(encoding="utf-8")
    )["changes"]
    return products, changes


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/products")
def products(page: int = Query(1, ge=1)) -> dict:
    items, _ = _load()
    start = (page - 1) * PRODUCT_PAGE_SIZE
    return {
        "page": page,
        "page_size": PRODUCT_PAGE_SIZE,
        "total": len(items),
        "items": items[start : start + PRODUCT_PAGE_SIZE],
    }


@app.get("/products/changes")
def product_changes(since: str = Query(START_DATE.isoformat())) -> dict:
    _, changes = _load()
    since_date = date.fromisoformat(since)
    items = [
        c for c in changes if date.fromisoformat(c["effective_date"]) >= since_date
    ]
    return {"since": since, "total": len(items), "changes": items}


if __name__ == "__main__":
    prods, chgs = _load()
    print(f"serving {len(prods)} products and {len(chgs)} changes from {LANDING}")
