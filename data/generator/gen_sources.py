"""Deterministic multi-source extract generator for the SSISRetailMart warehouse.

Produces three physically different sources under ``data/landing``:

1. ``stores.txt``        - fixed-width flat file (with 3 deliberately malformed rows)
2. ``sales_YYYYMMDD.csv``- one delimited CSV per business day (~8,000 rows/day)
3. ``products_page_*.json`` + ``product_changes.json`` - REST/JSON snapshots

Everything is driven by a single ``random.Random(42)`` instance so runs are byte
for byte reproducible.  A ``manifest.json`` records the exact counts produced so
tests can assert them without re-deriving the generator logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
N_BUSINESS_DAYS = 90
N_STORES = 200
N_PRODUCTS = 5000
ROWS_PER_DAY = 8000
BAD_ROW_RATE = 0.004
PRODUCT_PAGE_SIZE = 500
N_PRODUCT_CHANGES = 120
START_DATE = date(2024, 1, 1)

# Fixed-width stores.txt layout.  The SSIS Flat File connection manager declares
# the same widths; keep these two definitions in lockstep.
STORE_FIELD_WIDTHS = {
    "store_code": 6,
    "store_name": 40,
    "region": 12,
    "country": 3,
    "open_date": 10,
}
STORE_RECORD_WIDTH = sum(STORE_FIELD_WIDTHS.values())

REGIONS = [
    "Northeast",
    "Southeast",
    "Midwest",
    "Southwest",
    "West",
    "Northwest",
]

CATEGORIES = {
    "Electronics": ["Audio", "Computers", "Mobile", "Wearables"],
    "Clothing": ["Mens", "Womens", "Kids", "Outerwear"],
    "Home": ["Kitchen", "Furniture", "Decor", "Bedding"],
    "Grocery": ["Snacks", "Beverages", "Produce", "Pantry"],
    "Sports": ["Fitness", "Outdoor", "Team", "Cycling"],
    "Toys": ["Games", "Educational", "Plush", "Building"],
    "Beauty": ["Skincare", "Haircare", "Fragrance", "Makeup"],
    "Automotive": ["Fluids", "Tools", "Accessories", "Tires"],
}
BRANDS = [
    "Northwind",
    "Contoso",
    "Fabrikam",
    "AdventureWorks",
    "Litware",
    "Proseware",
    "Tailspin",
    "Wingtip",
]
CHANNELS = ["Store", "Online", "App"]
DISCOUNTS = [0, 5, 10, 15, 20]
DISCOUNT_WEIGHTS = [45, 20, 15, 12, 8]
CITIES = [
    "Austin",
    "Boston",
    "Chicago",
    "Denver",
    "El Paso",
    "Fresno",
    "Gilbert",
    "Honolulu",
    "Irving",
    "Jacksonville",
    "Knoxville",
    "Laredo",
    "Memphis",
    "Norfolk",
    "Oakland",
    "Portland",
    "Reno",
    "Seattle",
    "Tampa",
    "Utica",
]
STORE_TYPES = ["Retail Mart", "Supercenter", "Express", "Outlet", "Market"]

HERE = Path(__file__).resolve().parent
LANDING = HERE.parent / "landing"


def business_days(start: date, count: int) -> list[date]:
    """Return ``count`` consecutive weekdays starting at ``start``."""
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _pad(value: str, width: int) -> str:
    text = str(value)
    if len(text) > width:
        raise ValueError(f"value {text!r} exceeds fixed width {width}")
    return text.ljust(width)


def build_stores(rng: random.Random) -> tuple[list[dict], list[str]]:
    """Build 200 valid stores plus 3 malformed fixed-width raw lines."""
    stores: list[dict] = []
    for i in range(1, N_STORES + 1):
        code = f"ST{i:04d}"
        city = CITIES[(i - 1) % len(CITIES)]
        store_type = STORE_TYPES[(i - 1) % len(STORE_TYPES)]
        name = f"{city} {store_type} {i:03d}"
        region = REGIONS[(i - 1) % len(REGIONS)]
        open_date = date(2005, 1, 1) + timedelta(days=rng.randint(0, 6900))
        stores.append(
            {
                "store_code": code,
                "store_name": name,
                "region": region,
                "country": "USA",
                "open_date": open_date.isoformat(),
            }
        )

    # Three deliberately malformed fixed-width lines (appended at the end).
    malformed: list[str] = []
    # 1) invalid date (correct width, impossible month/day)
    base = dict(stores[0])
    base["open_date"] = "2020-13-45"
    malformed.append(_store_line(base))
    # 2) missing region (empty, padded to width)
    base = dict(stores[1])
    base["region"] = ""
    malformed.append(_store_line(base))
    # 3) over-long name -> record longer than the declared width
    overlong_name = ("OVERLONG-" * 10)[:45]
    long_line = (
        _pad("ST9999", STORE_FIELD_WIDTHS["store_code"])
        + _pad(overlong_name, STORE_FIELD_WIDTHS["store_name"] + 5)
        + _pad("West", STORE_FIELD_WIDTHS["region"])
        + _pad("USA", STORE_FIELD_WIDTHS["country"])
        + _pad("2010-01-01", STORE_FIELD_WIDTHS["open_date"])
    )
    malformed.append(long_line)
    return stores, malformed


def _store_line(store: dict) -> str:
    return (
        _pad(store["store_code"], STORE_FIELD_WIDTHS["store_code"])
        + _pad(store["store_name"], STORE_FIELD_WIDTHS["store_name"])
        + _pad(store["region"], STORE_FIELD_WIDTHS["region"])
        + _pad(store["country"], STORE_FIELD_WIDTHS["country"])
        + _pad(store["open_date"], STORE_FIELD_WIDTHS["open_date"])
    )


def build_products(rng: random.Random) -> list[dict]:
    products: list[dict] = []
    for i in range(1, N_PRODUCTS + 1):
        sku = f"P{i:05d}"
        category = list(CATEGORIES)[(i - 1) % len(CATEGORIES)]
        subcategory = CATEGORIES[category][(i - 1) % len(CATEGORIES[category])]
        brand = BRANDS[(i - 1) % len(BRANDS)]
        name = f"{brand} {subcategory} {i:05d}"
        list_price = round(rng.uniform(2.5, 899.0), 2)
        is_active = not (i % 37 == 0)
        products.append(
            {
                "sku": sku,
                "name": name,
                "category": category,
                "subcategory": subcategory,
                "brand": brand,
                "list_price": list_price,
                "is_active": is_active,
            }
        )
    return products


def build_product_changes(
    rng: random.Random, products: list[dict], days: list[date]
) -> list[dict]:
    """~120 price/category deltas that drive SCD Type 2 versioning."""
    chosen = rng.sample(range(len(products)), N_PRODUCT_CHANGES)
    changes: list[dict] = []
    categories = list(CATEGORIES)
    for idx, product_index in enumerate(chosen):
        product = products[product_index]
        change_date = days[rng.randint(1, len(days) - 1)]
        kind = "price" if idx % 2 == 0 else "category"
        # A change feed carries the full product record plus the effective date.
        change = dict(product)
        change["effective_date"] = change_date.isoformat()
        change["change_type"] = kind
        if kind == "price":
            factor = rng.choice([0.85, 0.9, 1.1, 1.15, 1.25])
            change["list_price"] = round(product["list_price"] * factor, 2)
        else:
            new_category = rng.choice(categories)
            if new_category == product["category"]:
                new_category = categories[(categories.index(new_category) + 1) % len(categories)]
            change["category"] = new_category
            change["subcategory"] = CATEGORIES[new_category][0]
        changes.append(change)
    changes.sort(key=lambda c: (c["effective_date"], c["sku"]))
    return changes


def _corrupt_row(row: dict, kind: str, rng: random.Random) -> dict:
    row = dict(row)
    if kind == "qty":
        row["qty"] = rng.choice(["abc", "N/A", "1O"])
    elif kind == "sku":
        row["sku"] = rng.choice(["SKU-UNKNOWN", "P99999", "NOTFOUND"])
    elif kind == "price":
        row["unit_price"] = f"-{abs(float(row['unit_price'])):.2f}"
    return row


def build_sales(
    rng: random.Random, products: list[dict], stores: list[dict], days: list[date]
) -> tuple[list[tuple[date, list[dict]]], dict]:
    skus = [p["sku"] for p in products]
    price_by_sku = {p["sku"]: p["list_price"] for p in products}
    store_codes = [s["store_code"] for s in stores]
    files: list[tuple[date, list[dict]]] = []
    bad_counts = {"qty": 0, "sku": 0, "price": 0}
    txn_seq = 0
    bad_seq = 0
    n_bad_per_day = round(ROWS_PER_DAY * BAD_ROW_RATE)
    kind_cycle = ["qty", "sku", "price"]
    for day in days:
        bad_indices = set(rng.sample(range(ROWS_PER_DAY), n_bad_per_day))
        rows: list[dict] = []
        for row_num in range(ROWS_PER_DAY):
            txn_seq += 1
            sku = rng.choice(skus)
            base_price = price_by_sku[sku]
            unit_price = round(base_price * rng.uniform(0.9, 1.12), 2)
            row = {
                "txn_id": f"TXN{txn_seq:09d}",
                "txn_ts": datetime.combine(
                    day,
                    datetime.min.time(),
                ).replace(
                    hour=rng.randint(8, 21),
                    minute=rng.randint(0, 59),
                    second=rng.randint(0, 59),
                ).isoformat(sep=" "),
                "store_code": rng.choice(store_codes),
                "sku": sku,
                "qty": rng.randint(1, 10),
                "unit_price": f"{unit_price:.2f}",
                "discount_pct": rng.choices(DISCOUNTS, weights=DISCOUNT_WEIGHTS)[0],
                "channel": rng.choice(CHANNELS),
            }
            if row_num in bad_indices:
                kind = kind_cycle[bad_seq % len(kind_cycle)]
                bad_seq += 1
                row = _corrupt_row(row, kind, rng)
                bad_counts[kind] += 1
            rows.append(row)
        files.append((day, rows))
    return files, bad_counts


SALES_FIELDS = [
    "txn_id",
    "txn_ts",
    "store_code",
    "sku",
    "qty",
    "unit_price",
    "discount_pct",
    "channel",
]


def write_stores(stores: list[dict], malformed: list[str]) -> dict:
    path = LANDING / "stores.txt"
    lines = [_store_line(s) for s in stores] + malformed
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "file": path.name,
        "valid_rows": len(stores),
        "malformed_rows": len(malformed),
        "total_rows": len(lines),
        "record_width": STORE_RECORD_WIDTH,
    }


def write_sales(files: list[tuple[date, list[dict]]], bad_counts: dict) -> dict:
    total = 0
    for day, rows in files:
        path = LANDING / f"sales_{day.strftime('%Y%m%d')}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=SALES_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        total += len(rows)
    return {
        "files": len(files),
        "rows": total,
        "bad_rows": sum(bad_counts.values()),
        "bad_by_type": bad_counts,
    }


def write_products(products: list[dict]) -> dict:
    pages = 0
    for start in range(0, len(products), PRODUCT_PAGE_SIZE):
        page = products[start : start + PRODUCT_PAGE_SIZE]
        pages += 1
        path = LANDING / f"products_page_{pages:03d}.json"
        payload = {
            "page": pages,
            "page_size": PRODUCT_PAGE_SIZE,
            "total": len(products),
            "items": page,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"pages": pages, "products": len(products), "page_size": PRODUCT_PAGE_SIZE}


def write_product_changes(changes: list[dict]) -> dict:
    path = LANDING / "product_changes.json"
    path.write_text(json.dumps({"changes": changes}, indent=2), encoding="utf-8")
    return {"file": path.name, "changes": len(changes)}


def generate(landing: Path = LANDING) -> dict:
    global LANDING
    LANDING = landing
    landing.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    days = business_days(START_DATE, N_BUSINESS_DAYS)

    stores, malformed = build_stores(rng)
    products = build_products(rng)
    changes = build_product_changes(rng, products, days)
    sales_files, bad_counts = build_sales(rng, products, stores, days)

    manifest = {
        "seed": SEED,
        "start_date": START_DATE.isoformat(),
        "business_days": len(days),
        "n_stores": N_STORES,
        "n_products": N_PRODUCTS,
        "rows_per_day": ROWS_PER_DAY,
        "stores": write_stores(stores, malformed),
        "sales": write_sales(sales_files, bad_counts),
        "products": write_products(products),
        "product_changes": write_product_changes(changes),
    }
    (landing / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--landing", type=Path, default=LANDING)
    args = parser.parse_args()
    manifest = generate(args.landing)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
