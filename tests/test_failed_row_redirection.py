"""Failed rows must land in audit.failed_rows with useful diagnostics."""

from __future__ import annotations

import pytest

from ssis_runtime import db

pytestmark = pytest.mark.integration


def _main_batch() -> int:
    with db.get_connection() as conn:
        return int(
            db.scalar(
                conn,
                "SELECT TOP 1 batch_id FROM audit.etl_batch "
                "GROUP BY batch_id ORDER BY SUM(rows_read) DESC",
            )
        )


def test_total_failed_rows_and_breakdown():
    batch_id = _main_batch()
    with db.get_connection() as conn:
        total = db.scalar(
            conn,
            "SELECT COUNT(*) FROM audit.failed_rows WHERE batch_id=%s",
            (batch_id,),
        )
        by_component = {
            row["component"]: row["n"]
            for row in db.query_dicts(
                conn,
                "SELECT component, COUNT(*) AS n FROM audit.failed_rows "
                "WHERE batch_id=%s GROUP BY component",
                (batch_id,),
            )
        }
        described = db.scalar(
            conn,
            "SELECT COUNT(*) FROM audit.failed_rows WHERE batch_id=%s "
            "AND (error_description IS NULL OR error_description='')",
            (batch_id,),
        )
    assert total == 2883
    assert by_component["Derived Column"] == 961
    assert by_component["Conditional Split"] == 1921
    assert by_component["Stores Flat File Source"] == 1
    assert described == 0


def test_package_level_reject_counts():
    batch_id = _main_batch()
    with db.get_connection() as conn:
        counts = {
            row["package_name"]: row["rows_rejected"]
            for row in db.query_dicts(
                conn,
                "SELECT package_name, rows_rejected FROM audit.etl_batch WHERE batch_id=%s",
                (batch_id,),
            )
        }
    assert counts["LoadStores"] == 3
    assert counts["LoadSalesCsv"] == 2880
