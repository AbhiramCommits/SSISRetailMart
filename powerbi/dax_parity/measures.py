"""Python reimplementation of the DAX measure semantics.

Each function mirrors the T-SQL in ``sql/checks/measure_parity.sql`` so that
``tests/test_dax_parity.py`` can verify the DAX measures against real warehouse
data without Power BI Desktop.
"""

from __future__ import annotations

from decimal import Decimal

from ssis_runtime import db

MEASURE_NAMES = [
    "Net Sales",
    "Gross Sales",
    "Discount %",
    "Units Sold",
    "Avg Order Value",
    "Net Sales LY",
    "Net Sales YoY %",
    "Net Sales MTD",
    "Stockout Days",
    "Stockout Rate %",
    "Lost Sales Estimate",
    "Active SKU Count",
    "Rejected Row Rate %",
    "Load Success Rate %",
]


def _f(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def load_warehouse() -> dict:
    """Pull the raw warehouse rows the measures are evaluated over."""
    with db.get_connection() as conn:
        fact = db.query_dicts(
            conn,
            "SELECT f.date_key, f.product_sk, f.store_sk, f.txn_id, f.qty, "
            "f.gross_amount, f.discount_amount, f.net_amount, d.year, d.month, st.region "
            "FROM dw.fact_sales f "
            "JOIN dw.dim_date d ON d.date_key=f.date_key "
            "JOIN dw.dim_store st ON st.store_sk=f.store_sk",
        )
        inventory = db.query_dicts(
            conn,
            "SELECT i.date_key, i.product_sk, i.is_stockout, d.year, d.month, st.region "
            "FROM dw.fact_inventory_snapshot i "
            "JOIN dw.dim_date d ON d.date_key=i.date_key "
            "JOIN dw.dim_store st ON st.store_sk=i.store_sk",
        )
        active_sku = db.scalar(
            conn,
            "SELECT COUNT(*) FROM dw.dim_product WHERE is_current=1 AND product_sk<>-1",
        )
        batches = db.query_dicts(
            conn, "SELECT status, rows_read, rows_rejected FROM audit.etl_batch"
        )
    return {
        "fact": fact,
        "inventory": inventory,
        "active_sku": int(active_sku or 0),
        "batches": batches,
    }


def eval_measures(data: dict, year=None, month=None, region=None) -> dict:
    fact = [
        r
        for r in data["fact"]
        if (year is None or r["year"] == year)
        and (month is None or r["month"] == month)
        and (region is None or r["region"] == region)
    ]
    inventory = [
        r
        for r in data["inventory"]
        if (year is None or r["year"] == year)
        and (month is None or r["month"] == month)
        and (region is None or r["region"] == region)
    ]

    net = _f(sum((_f(r["net_amount"]) or 0 for r in fact), 0)) if fact else None
    gross = _f(sum((_f(r["gross_amount"]) or 0 for r in fact), 0)) if fact else None
    discount = _f(sum((_f(r["discount_amount"]) or 0 for r in fact), 0)) if fact else None
    units = _f(sum((r["qty"] for r in fact), 0)) if fact else None
    txns = len({r["txn_id"] for r in fact}) if fact else 0

    discount_pct = None if not gross else discount / gross
    aov = None if not txns else net / txns

    prev_year = (year if year is not None else 1900) - 1
    ly_rows = [
        r
        for r in fact
        if r["year"] == prev_year and (month is None or r["month"] == month)
    ]
    ly = _f(sum((_f(r["net_amount"]) or 0 for r in ly_rows), 0)) if ly_rows else None
    yoy = None if not ly else (net - ly) / ly

    if fact:
        max_key = max(r["date_key"] for r in fact)
        max_year, max_month = max_key // 10000, (max_key // 100) % 100
        mtd = _f(
            sum(
                (_f(r["net_amount"]) or 0 for r in fact
                 if r["year"] == max_year and r["month"] == max_month),
                0,
            )
        )
    else:
        mtd = None

    stockout_days = len({r["date_key"] for r in inventory if r["is_stockout"]})
    stockout_rate = (
        _f(sum(1 for r in inventory if r["is_stockout"])) / len(inventory)
        if inventory
        else None
    )

    # Decimal arithmetic mirrors the T-SQL DECIMAL division for parity.
    net_by_product: dict = {}
    qty_by_product: dict = {}
    for r in fact:
        product = r["product_sk"]
        net_by_product[product] = net_by_product.get(product, Decimal(0)) + (
            r["net_amount"] if isinstance(r["net_amount"], Decimal) else Decimal(str(r["net_amount"]))
        )
        qty_by_product[product] = qty_by_product.get(product, 0) + int(r["qty"])
    quantum = Decimal("0.000001")
    avpu = {
        k: (
            (net_by_product[k] / Decimal(qty_by_product[k])).quantize(quantum)
            if qty_by_product[k]
            else None
        )
        for k in net_by_product
    }
    lost = sum(
        (avpu.get(r["product_sk"]) or Decimal(0) for r in inventory if r["is_stockout"]),
        Decimal(0),
    )

    rows_read = sum(r["rows_read"] for r in data["batches"])
    rows_rejected = sum(r["rows_rejected"] for r in data["batches"])
    rejected_rate = None if rows_read == 0 else rows_rejected / rows_read
    total = len(data["batches"])
    load_success = (
        None
        if total == 0
        else sum(1 for r in data["batches"] if r["status"] == "SUCCESS") / total
    )

    return {
        "Net Sales": net,
        "Gross Sales": gross,
        "Discount %": discount_pct,
        "Units Sold": units,
        "Avg Order Value": aov,
        "Net Sales LY": ly,
        "Net Sales YoY %": yoy,
        "Net Sales MTD": mtd,
        "Stockout Days": _f(stockout_days),
        "Stockout Rate %": stockout_rate,
        "Lost Sales Estimate": lost,
        "Active SKU Count": _f(data["active_sku"]),
        "Rejected Row Rate %": rejected_rate,
        "Load Success Rate %": load_success,
    }


def sql_measures(year=None, month=None, region=None) -> dict:
    with db.get_connection() as conn:
        rows = db.query_dicts(
            conn,
            "EXEC dq.sp_measure_parity @year=%s, @month=%s, @region=%s",
            (year, month, region),
        )
    return {r["measure_name"]: r["measure_value"] for r in rows}
