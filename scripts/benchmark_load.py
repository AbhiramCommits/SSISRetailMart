"""Benchmark the warehouse load.

Measures a cold full load, a warm incremental fact load, and fact-insert timings
with indexes enabled vs disabled.  Writes results/benchmarks.json and
results/benchmarks.md from the actual runs.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import apply_sql  # noqa: E402
from scripts.run_etl import PACKAGES  # noqa: E402
from ssis_runtime import db  # noqa: E402
from ssis_runtime.engine import execute_package  # noqa: E402

RESULTS = ROOT / "results"
BATCH_ID = 20240603000000


def _time(fn) -> tuple[object, int]:
    start = time.time()
    result = fn()
    return result, int((time.time() - start) * 1000)


def _run_full_load() -> tuple[list[dict], int]:
    started = time.time()
    results = []
    for name in PACKAGES:
        result = execute_package(
            ROOT / "ssis" / "packages" / f"{name}.dtsx",
            {"BatchId": BATCH_ID, "LandingPath": "data/landing/"},
        )
        results.append(result.to_dict())
    return results, int((time.time() - started) * 1000)


def _fact_columns() -> list[str]:
    with db.get_connection() as conn:
        rows = db.query(
            conn,
            "SELECT c.name FROM sys.columns c JOIN sys.tables t ON t.object_id=c.object_id "
            "JOIN sys.schemas s ON s.schema_id=t.schema_id "
            "WHERE s.name='dw' AND t.name='fact_sales' AND c.is_identity=0 ORDER BY c.column_id",
        )
    return [r[0] for r in rows]


def _fact_insert_benchmark() -> dict:
    """Isolate index-maintenance cost: identical inserts into a heap vs an
    equivalently-indexed table, both sourced from dw.fact_sales."""
    columns = _fact_columns()
    col_list = ", ".join(db.quote_ident(c) for c in columns)
    with db.get_connection() as conn:
        for table in ("dw.bench_heap", "dw.bench_idx"):
            db.execute(conn, f"IF OBJECT_ID('{table}','U') IS NOT NULL DROP TABLE {table}")
            db.execute(conn, f"SELECT TOP 0 * INTO {table} FROM dw.fact_sales")
        db.execute(conn, "CREATE CLUSTERED INDEX bc ON dw.bench_idx (date_key, store_sk)")
        db.execute(conn, "CREATE NONCLUSTERED INDEX bp ON dw.bench_idx (product_sk)")
        db.execute(conn, "CREATE UNIQUE NONCLUSTERED INDEX bt ON dw.bench_idx (txn_id)")

        def _insert(table: str) -> int:
            with db.get_connection() as c2:
                return db.execute(
                    c2,
                    f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM dw.fact_sales",
                )

        _, index_off_ms = _time(lambda: _insert("dw.bench_heap"))
        rows, index_on_ms = _time(lambda: _insert("dw.bench_idx"))

        for table in ("dw.bench_heap", "dw.bench_idx"):
            db.execute(conn, f"DROP TABLE {table}")

    return {
        "rows": int(rows),
        "index_on_ms": index_on_ms,
        "index_off_ms": index_off_ms,
        "index_on_rows_per_sec": round(rows / (index_on_ms / 1000.0), 1) if index_on_ms else 0,
        "index_off_rows_per_sec": round(rows / (index_off_ms / 1000.0), 1) if index_off_ms else 0,
    }


def collect() -> dict:
    apply_sql.apply_all(reset=True, verbose=False)

    cold_results, cold_wall_ms = _run_full_load()

    _, warm_ms = _time(
        lambda: execute_package(
            ROOT / "ssis" / "packages" / "LoadFactSales.dtsx",
            {"BatchId": BATCH_ID, "LandingPath": "data/landing/"},
        )
    )

    fact_insert = _fact_insert_benchmark()

    for pkg in cold_results:
        pkg["rows_per_sec"] = (
            round(pkg["rows_read"] / (pkg["duration_ms"] / 1000.0), 1)
            if pkg["duration_ms"]
            else 0.0
        )

    return {
        "batch_id": BATCH_ID,
        "cold_load": {
            "wall_clock_ms": cold_wall_ms,
            "wall_clock_seconds": round(cold_wall_ms / 1000.0, 3),
            "packages": cold_results,
        },
        "warm_incremental_load": {"duration_ms": warm_ms, "rows_inserted": 0},
        "fact_insert": fact_insert,
    }


def to_markdown(b: dict) -> str:
    lines = [
        "# RetailMart load benchmarks",
        "",
        f"_Batch `{b['batch_id']}`._",
        "",
        "## Cold full load",
        "",
        f"Wall clock: **{b['cold_load']['wall_clock_seconds']:,} s**",
        "",
        "| Package | Duration (ms) | Rows read | Rows/sec |",
        "| --- | ---: | ---: | ---: |",
    ]
    for p in b["cold_load"]["packages"]:
        lines.append(
            f"| {p['package']} | {p['duration_ms']:,} | {p['rows_read']:,} | {p['rows_per_sec']:,} |"
        )
    f = b["fact_insert"]
    lines += [
        "",
        "## Warm incremental fact load",
        "",
        f"Re-running `LoadFactSales` on an already-loaded batch: **{b['warm_incremental_load']['duration_ms']:,} ms** "
        f"({b['warm_incremental_load']['rows_inserted']} rows inserted).",
        "",
        "## Fact insert: indexes on vs off",
        "",
        "| Indexes | Duration (ms) | Rows/sec | Rows |",
        "| --- | ---: | ---: | ---: |",
        f"| ON | {f['index_on_ms']:,} | {f['index_on_rows_per_sec']:,} | {f['rows']:,} |",
        f"| OFF | {f['index_off_ms']:,} | {f['index_off_rows_per_sec']:,} | {f['rows']:,} |",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    benchmarks = collect()
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "benchmarks.json").write_text(
        json.dumps(benchmarks, indent=2), encoding="utf-8"
    )
    (RESULTS / "benchmarks.md").write_text(to_markdown(benchmarks), encoding="utf-8")
    print(json.dumps(benchmarks["fact_insert"], indent=2))
    print("wrote results/benchmarks.json and results/benchmarks.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
