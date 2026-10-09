"""SCD Type 2 behaviour driven by the REST changes feed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import product_api
from ssis_runtime import db

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def changes():
    client = TestClient(product_api.app)
    response = client.get("/products/changes")
    assert response.status_code == 200
    return response.json()["changes"]


def test_changes_feed_size(changes):
    assert len(changes) == 120
    assert all({"sku", "effective_date", "change_type"} <= set(c) for c in changes)


def test_expired_rows_have_valid_to():
    with db.get_connection() as conn:
        expired_without_end = db.scalar(
            conn,
            "SELECT COUNT(*) FROM dw.dim_product "
            "WHERE is_current=0 AND product_sk<>-1 AND valid_to IS NULL",
        )
        current_with_end = db.scalar(
            conn,
            "SELECT COUNT(*) FROM dw.dim_product WHERE is_current=1 AND valid_to IS NOT NULL",
        )
    assert expired_without_end == 0
    assert current_with_end == 0


def test_exactly_one_current_row_per_sku():
    with db.get_connection() as conn:
        offenders = db.scalar(
            conn,
            "SELECT COUNT(*) FROM (SELECT sku FROM dw.dim_product "
            "WHERE product_sk<>-1 GROUP BY sku HAVING SUM(CAST(is_current AS INT))<>1) x",
        )
    assert offenders == 0


def test_every_changed_sku_has_multiple_versions(changes):
    with db.get_connection() as conn:
        versions = {
            row[0]: row[1]
            for row in db.query(
                conn,
                "SELECT sku, COUNT(*) FROM dw.dim_product WHERE product_sk<>-1 GROUP BY sku",
            )
        }
    for change in changes:
        assert versions.get(change["sku"], 0) >= 2, change["sku"]


def test_current_version_reflects_change(changes):
    with db.get_connection() as conn:
        current = {
            row["sku"]: row
            for row in db.query_dicts(
                conn,
                "SELECT sku, list_price, category FROM dw.dim_product "
                "WHERE is_current=1 AND product_sk<>-1",
            )
        }
    for change in changes:
        row = current[change["sku"]]
        if change["change_type"] == "price":
            assert abs(float(row["list_price"]) - float(change["list_price"])) < 0.01
        else:
            assert row["category"] == change["category"]


def test_fact_rows_point_at_version_valid_on_sale_date():
    with db.get_connection() as conn:
        violations = db.scalar(
            conn,
            "SELECT COUNT(*) FROM dw.fact_sales f "
            "JOIN dw.dim_product p ON p.product_sk=f.product_sk "
            "WHERE NOT (p.valid_from <= DATEFROMPARTS(f.date_key/10000,(f.date_key/100)%100,f.date_key%100) "
            "AND (p.valid_to IS NULL OR p.valid_to >= DATEFROMPARTS(f.date_key/10000,(f.date_key/100)%100,f.date_key%100)))",
        )
    assert violations == 0
