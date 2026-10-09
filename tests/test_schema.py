"""Apply the warehouse DDL and assert the contract the pipeline depends on."""

from __future__ import annotations

import pytest

from scripts import apply_sql
from ssis_runtime import db

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _schema():
    apply_sql.apply_all(verbose=False)


def _table_exists(conn, schema: str, table: str) -> bool:
    return (
        db.scalar(
            conn,
            "SELECT COUNT(*) FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id "
            "WHERE s.name=%s AND t.name=%s",
            (schema, table),
        )
        == 1
    )


def _index_exists(conn, table: str, index: str) -> bool:
    return (
        db.scalar(
            conn,
            "SELECT COUNT(*) FROM sys.indexes WHERE name=%s AND object_id=OBJECT_ID(%s)",
            (index, table),
        )
        == 1
    )


def test_tables_exist():
    with db.get_connection() as conn:
        for schema, table in [
            ("stg", "stores_raw"),
            ("stg", "sales_raw"),
            ("stg", "products_raw"),
            ("dw", "dim_date"),
            ("dw", "dim_store"),
            ("dw", "dim_product"),
            ("dw", "fact_sales"),
            ("dw", "fact_inventory_snapshot"),
            ("audit", "etl_batch"),
            ("audit", "row_count_check"),
            ("audit", "checksum_check"),
            ("audit", "failed_rows"),
            ("dq", "assertion_result"),
        ]:
            assert _table_exists(conn, schema, table), f"missing {schema}.{table}"


def test_indexes_exist():
    with db.get_connection() as conn:
        assert _index_exists(conn, "dw.fact_sales", "CIX_fact_sales_date_store")
        assert _index_exists(conn, "dw.fact_sales", "IX_fact_sales_product")
        assert _index_exists(conn, "dw.fact_sales", "UQ_fact_sales_txn")
        assert _index_exists(
            conn, "dw.fact_inventory_snapshot", "CIX_fact_inv_date"
        )
        assert _index_exists(conn, "dw.dim_product", "IX_dim_product_sku_current")


def test_unknown_members():
    with db.get_connection() as conn:
        assert db.scalar(conn, "SELECT store_code FROM dw.dim_store WHERE store_sk=-1") == "UNKNOWN"
        assert db.scalar(conn, "SELECT sku FROM dw.dim_product WHERE product_sk=-1") == "UNKNOWN"
        assert db.scalar(conn, "SELECT is_unknown FROM dw.dim_store WHERE store_sk=-1") is True


def test_dim_date_populated():
    with db.get_connection() as conn:
        count = db.scalar(conn, "SELECT COUNT(*) FROM dw.dim_date")
        assert count == 3287
        assert db.scalar(conn, "SELECT COUNT(*) FROM dw.dim_date WHERE is_weekend=1") == 938
        assert db.scalar(conn, "SELECT COUNT(*) FROM dw.dim_date WHERE month=12 AND day_of_month=25") == 9
        assert db.scalar(conn, "SELECT date_key FROM dw.dim_date WHERE full_date='2024-01-01'") == 20240101


def test_staging_is_untyped_varchar():
    with db.get_connection() as conn:
        rows = db.query(
            conn,
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA='stg' AND TABLE_NAME='sales_raw' AND COLUMN_NAME IN "
            "('qty_raw','unit_price_raw','discount_pct_raw','txn_ts_raw')",
        )
        assert rows, "expected staging columns"
        assert all(dtype == "varchar" for _, dtype in rows)
