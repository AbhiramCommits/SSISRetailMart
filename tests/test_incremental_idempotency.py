"""Re-running the fact load must not duplicate transactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from ssis_runtime import db
from ssis_runtime.engine import execute_package

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ssis" / "packages" / "LoadFactSales.dtsx"

pytestmark = pytest.mark.integration


def _main_batch() -> int:
    with db.get_connection() as conn:
        return int(
            db.scalar(
                conn,
                "SELECT TOP 1 batch_id FROM stg.sales_raw WHERE is_valid=1 "
                "GROUP BY batch_id ORDER BY COUNT(*) DESC",
            )
        )


def _fact_count() -> int:
    with db.get_connection() as conn:
        return int(db.scalar(conn, "SELECT COUNT(*) FROM dw.fact_sales"))


def _duplicate_txns() -> int:
    with db.get_connection() as conn:
        return int(
            db.scalar(
                conn,
                "SELECT COUNT(*) FROM (SELECT txn_id FROM dw.fact_sales "
                "GROUP BY txn_id HAVING COUNT(*)>1) x",
            )
        )


def test_rerun_fact_load_is_idempotent():
    batch_id = _main_batch()
    before = _fact_count()
    assert before > 0

    first = execute_package(PACKAGE, {"BatchId": batch_id})
    after_first = _fact_count()
    second = execute_package(PACKAGE, {"BatchId": batch_id})

    assert first.status == "SUCCESS" and second.status == "SUCCESS"
    # fact rows are not re-inserted and no transaction is duplicated
    assert after_first == before
    assert _fact_count() == before
    assert _duplicate_txns() == 0
