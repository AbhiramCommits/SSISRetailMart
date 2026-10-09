"""Export real warehouse metrics to results/metrics.json and results/metrics.md."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from powerbi.dax_parity import measures  # noqa: E402
from ssis_runtime import db  # noqa: E402

RESULTS = ROOT / "results"


def latest_batch(conn) -> int:
    return int(
        db.scalar(
            conn,
            "SELECT TOP 1 batch_id FROM audit.etl_batch "
            "GROUP BY batch_id ORDER BY SUM(rows_read) DESC",
        )
        or 0
    )


def collect() -> dict:
    with db.get_connection() as conn:
        batch_id = latest_batch(conn)
        scalar = db.scalar
        fact_rows = scalar(conn, "SELECT COUNT(*) FROM dw.fact_sales")
        distinct_skus = scalar(
            conn, "SELECT COUNT(DISTINCT product_sk) FROM dw.fact_sales WHERE product_sk <> -1"
        )
        distinct_stores = scalar(conn, "SELECT COUNT(DISTINCT store_sk) FROM dw.fact_sales")
        distinct_days = scalar(conn, "SELECT COUNT(DISTINCT date_key) FROM dw.fact_sales")
        scd2_versions = scalar(
            conn,
            "SELECT COUNT(*) FROM dw.dim_product WHERE product_sk<>-1",
        )
        scd2_multi = scalar(
            conn,
            "SELECT COUNT(*) FROM (SELECT sku FROM dw.dim_product WHERE product_sk<>-1 "
            "GROUP BY sku HAVING COUNT(*)>1) x",
        )
        dim_products = scalar(conn, "SELECT COUNT(DISTINCT sku) FROM dw.dim_product WHERE product_sk<>-1")
        dim_stores = scalar(conn, "SELECT COUNT(*) FROM dw.dim_store WHERE is_unknown=0")
        rejected = scalar(
            conn, "SELECT ISNULL(SUM(rows_rejected),0) FROM audit.etl_batch WHERE batch_id=%s", (batch_id,)
        )
        read = scalar(
            conn, "SELECT ISNULL(SUM(rows_read),0) FROM audit.etl_batch WHERE batch_id=%s", (batch_id,)
        )
        checksum_matches = scalar(
            conn, "SELECT COUNT(*) FROM audit.checksum_check WHERE batch_id=%s AND matched=1", (batch_id,)
        )
        checksum_total = scalar(
            conn, "SELECT COUNT(*) FROM audit.checksum_check WHERE batch_id=%s", (batch_id,)
        )
        assertions = db.query_dicts(
            conn,
            "SELECT assertion_name, status FROM dq.assertion_result WHERE batch_id=%s "
            "ORDER BY assertion_name",
            (batch_id,),
        )
        packages = db.query_dicts(
            conn,
            "SELECT package_name, status, rows_read, rows_inserted, rows_rejected, duration_ms "
            "FROM audit.etl_batch WHERE batch_id=%s ORDER BY etl_batch_sk",
            (batch_id,),
        )
        wall_clock = scalar(
            conn,
            "SELECT DATEDIFF(SECOND, MIN(started_at), MAX(ended_at)) FROM audit.etl_batch WHERE batch_id=%s",
            (batch_id,),
        )
        failed = db.query_dicts(
            conn,
            "SELECT component, error_column, COUNT(*) AS n FROM audit.failed_rows "
            "WHERE batch_id=%s GROUP BY component, error_column ORDER BY n DESC",
            (batch_id,),
        )

    for pkg in packages:
        pkg["rows_per_sec"] = (
            round(pkg["rows_read"] / (pkg["duration_ms"] / 1000.0), 1)
            if pkg["duration_ms"]
            else 0.0
        )

    all_time = measures.eval_measures(measures.load_warehouse())
    assertions_passed = sum(1 for a in assertions if a["status"] == "PASS")

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "batch_id": batch_id,
        "fact_rows": fact_rows,
        "distinct_skus": distinct_skus,
        "distinct_stores": distinct_stores,
        "distinct_days": distinct_days,
        "dim_products": dim_products,
        "dim_stores": dim_stores,
        "scd2_versions": scd2_versions,
        "scd2_products_with_multiple_versions": scd2_multi,
        "rejected_rows": rejected,
        "rejected_row_rate": round(rejected / read, 6) if read else 0,
        "checksum_matches": checksum_matches,
        "checksum_total": checksum_total,
        "assertions_passed": assertions_passed,
        "assertions_total": len(assertions),
        "assertions": assertions,
        "packages": packages,
        "wall_clock_seconds": wall_clock,
        "failed_rows_breakdown": failed,
        "measures": {k: (None if v is None else float(v)) for k, v in all_time.items()},
        "stockout_rate": float(all_time["Stockout Rate %"]),
    }


def to_markdown(m: dict) -> str:
    lines = [
        "# RetailMart load metrics",
        "",
        f"_Generated {m['generated_at']} from batch `{m['batch_id']}`._",
        "",
        "## Warehouse",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| fact_sales rows | {m['fact_rows']:,} |",
        f"| distinct SKUs (fact) | {m['distinct_skus']:,} |",
        f"| distinct stores (fact) | {m['distinct_stores']:,} |",
        f"| distinct days (fact) | {m['distinct_days']:,} |",
        f"| dim_product rows | {m['dim_products']:,} |",
        f"| dim_store rows | {m['dim_stores']:,} |",
        f"| SCD2 version rows | {m['scd2_versions']:,} |",
        f"| products with >1 version | {m['scd2_products_with_multiple_versions']:,} |",
        f"| rejected rows | {m['rejected_rows']:,} |",
        f"| rejected-row rate | {m['rejected_row_rate']:.4%} |",
        f"| checksum matches | {m['checksum_matches']}/{m['checksum_total']} |",
        f"| DQ assertions passed | {m['assertions_passed']}/{m['assertions_total']} |",
        f"| end-to-end wall clock | {m['wall_clock_seconds']:,} s |",
        "",
        "## Packages",
        "",
        "| Package | Status | Rows read | Inserted | Rejected | Duration (ms) | Rows/sec |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for p in m["packages"]:
        lines.append(
            f"| {p['package_name']} | {p['status']} | {p['rows_read']:,} | "
            f"{p['rows_inserted']:,} | {p['rows_rejected']:,} | {p['duration_ms']:,} | "
            f"{p['rows_per_sec']:,} |"
        )
    lines += ["", "## Measures (all-time)", "", "| Measure | Value |", "| --- | --- |"]
    for name, value in m["measures"].items():
        rendered = "n/a" if value is None else f"{value:,.4f}"
        lines.append(f"| {name} | {rendered} |")
    lines += [
        "",
        "## Failed rows",
        "",
        "| Component | Error column | Rows |",
        "| --- | --- | ---: |",
    ]
    for f in m["failed_rows_breakdown"]:
        lines.append(f"| {f['component']} | {f['error_column'] or '-'} | {f['n']:,} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    metrics = collect()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (RESULTS / "metrics.md").write_text(to_markdown(metrics), encoding="utf-8")
    print(f"wrote results/metrics.json and results/metrics.md (batch {metrics['batch_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
