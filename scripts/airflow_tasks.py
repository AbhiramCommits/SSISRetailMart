"""Python callables backing the Airflow tasks.

Keeping these out of the DAG module makes them unit-testable without an Airflow
scheduler.  The DAG imports them and wires them into PythonOperators.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ssis_runtime import db  # noqa: E402

RESULTS_DIR = ROOT / "results"
CONTROL_PACKAGE = "retail_mart_etl"


def _fail(message: str):
    try:
        from airflow.exceptions import AirflowFailException
    except ImportError:  # pragma: no cover - airflow always present in DAG runs
        raise RuntimeError(message) from None
    raise AirflowFailException(message)


def batch_id_from_context(context: dict) -> int:
    """Derive a numeric BatchId from the Airflow run (templated ts_nodash)."""
    raw = context.get("ts_nodash") or context.get("ds_nodash") or "0"
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return int(digits) if digits else 0


def start_batch(**context) -> int:
    batch_id = batch_id_from_context(context)
    with db.get_connection() as conn:
        db.execute(
            conn,
            "EXEC audit.sp_start_batch @batch_id=%s, @package_name=%s",
            (batch_id, CONTROL_PACKAGE),
        )
    return batch_id


def build_inventory_snapshot(**context) -> int:
    batch_id = batch_id_from_context(context)
    with db.get_connection() as conn:
        rows = db.query_dicts(
            conn,
            "EXEC dw.sp_build_inventory_snapshot @batch_id=%s",
            (batch_id,),
        )
    return int(rows[0]["rows_inserted"]) if rows else 0


def run_assertions(batch_id: int) -> list[dict]:
    """Run every dq assertion for a batch and return the result rows."""
    with db.get_connection() as conn:
        return db.query_dicts(
            conn,
            "EXEC dq.sp_run_assertions @batch_id=%s",
            (batch_id,),
        )


def run_dq_assertions(**context) -> dict:
    batch_id = batch_id_from_context(context)
    rows = run_assertions(batch_id)
    failures = [r for r in rows if r["status"] != "PASS"]
    summary = {
        "batch_id": batch_id,
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "failures": [r["assertion_name"] for r in failures],
    }
    if failures:
        _fail(f"data-quality gates failed: {summary['failures']}")
    return summary


def publish_load_health(**context) -> str:
    batch_id = batch_id_from_context(context)
    with db.get_connection() as conn:
        packages = db.query_dicts(
            conn,
            "SELECT package_name, status, rows_read, rows_inserted, rows_updated, "
            "rows_rejected, duration_ms FROM audit.etl_batch WHERE batch_id=%s "
            "ORDER BY etl_batch_sk",
            (batch_id,),
        )
        checksums = db.query_dicts(
            conn,
            "SELECT column_name, matched FROM audit.checksum_check WHERE batch_id=%s "
            "ORDER BY check_sk",
            (batch_id,),
        )
        assertions = db.query_dicts(
            conn,
            "SELECT assertion_name, status, observed_value, threshold "
            "FROM dq.assertion_result WHERE batch_id=%s ORDER BY assertion_name",
            (batch_id,),
        )

    passed = sum(1 for a in assertions if a["status"] == "PASS")
    payload = {
        "batch_id": batch_id,
        "packages": packages,
        "checksums": checksums,
        "assertions": assertions,
        "assertion_pass_count": passed,
        "assertion_fail_count": len(assertions) - passed,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / "load_health.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(out)


def end_batch(**context) -> str:
    batch_id = batch_id_from_context(context)
    failed = False
    try:
        instances = context["dag_run"].get_task_instances()
        failed = any(
            ti.state == "failed" for ti in instances if ti.task_id != "end_batch"
        )
    except Exception:  # noqa: BLE001 - best effort status
        failed = False
    status = "FAILED" if failed else "SUCCESS"
    with db.get_connection() as conn:
        db.execute(
            conn,
            "EXEC audit.sp_end_batch @batch_id=%s, @package_name=%s, @status=%s",
            (batch_id, CONTROL_PACKAGE, status),
        )
    return status
