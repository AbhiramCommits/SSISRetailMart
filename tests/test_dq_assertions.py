"""Assert that injected bad data fails a gate and makes the Airflow task raise."""

from __future__ import annotations

import pytest
from airflow.exceptions import AirflowFailException

from scripts.airflow_tasks import run_assertions, run_dq_assertions
from ssis_runtime import db

pytestmark = pytest.mark.integration

CONTEXT = {"ts_nodash": "20240101T000000"}


def _status(rows, name):
    return next((r["status"] for r in rows if r["assertion_name"] == name), None)


def test_orphan_product_key_fails_gate_and_task():
    injected = "TEST-ORPHAN-0001"
    with db.get_connection() as conn:
        db.execute(conn, "DELETE FROM dw.fact_sales WHERE txn_id=%s", (injected,))
        db.execute(
            conn,
            "INSERT INTO dw.fact_sales (date_key, product_sk, store_sk, txn_id, qty, "
            "unit_price, discount_pct, gross_amount, discount_amount, net_amount, channel, batch_id) "
            "VALUES (20240101, 999999, -1, %s, 1, 1, 0, 1, 0, 1, 'Test', 0)",
            (injected,),
        )
    try:
        rows = run_assertions(0)
        assert _status(rows, "no_orphan_product_keys") == "FAIL"
        with pytest.raises(AirflowFailException):
            run_dq_assertions(**CONTEXT)
    finally:
        with db.get_connection() as conn:
            db.execute(conn, "DELETE FROM dw.fact_sales WHERE txn_id=%s", (injected,))


def test_duplicate_txn_id_fails_gate():
    with db.get_connection() as conn:
        original = db.query_dicts(conn, "SELECT TOP 1 * FROM dw.fact_sales ORDER BY sale_sk")[0]
        db.execute(conn, "ALTER INDEX UQ_fact_sales_txn ON dw.fact_sales DISABLE")
    injected = original["txn_id"]
    try:
        with db.get_connection() as conn:
            db.execute(
                conn,
                "INSERT INTO dw.fact_sales (date_key, product_sk, store_sk, txn_id, qty, "
                "unit_price, discount_pct, gross_amount, discount_amount, net_amount, channel, batch_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    original["date_key"],
                    original["product_sk"],
                    original["store_sk"],
                    injected,
                    original["qty"],
                    original["unit_price"],
                    original["discount_pct"],
                    original["gross_amount"],
                    original["discount_amount"],
                    original["net_amount"],
                    original["channel"],
                    0,
                ),
            )
        rows = run_assertions(0)
        assert _status(rows, "no_duplicate_txn_id") == "FAIL"
        with pytest.raises(AirflowFailException):
            run_dq_assertions(**CONTEXT)
    finally:
        with db.get_connection() as conn:
            db.execute(
                conn,
                "DELETE FROM dw.fact_sales WHERE txn_id=%s AND sale_sk NOT IN "
                "(SELECT MIN(sale_sk) FROM dw.fact_sales WHERE txn_id=%s)",
                (injected, injected),
            )
            db.execute(conn, "ALTER INDEX UQ_fact_sales_txn ON dw.fact_sales REBUILD")
        rows = run_assertions(0)
        assert _status(rows, "no_duplicate_txn_id") == "PASS"
