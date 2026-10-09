"""Unit and integration tests for the dtexec-compatible runtime."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from ssis_runtime import db
from ssis_runtime.dtsx_parser import parse_package
from ssis_runtime.engine import execute_package
from ssis_runtime.expressions import CastError, evaluate

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "ssis" / "packages"
LANDING = ROOT / "data" / "landing"


# --- expression evaluator (unit) ----------------------------------------
def test_arithmetic_and_ternary():
    row = {"qty": "3", "price": "2.50"}
    assert evaluate("(DT_I4)[qty] * (DT_DECIMAL,2)[price]", row, {}) == 7.5
    assert evaluate("(DT_I4)[qty] > 2 ? \"big\" : \"small\"", row, {}) == "big"


def test_string_functions():
    row = {"name": "  acme widget  "}
    assert evaluate("TRIM(UPPER([name]))", row, {}) == "ACME WIDGET"
    assert evaluate("SUBSTRING(TRIM([name]),1,4)", row, {}) == "acme"
    assert evaluate("LEN(TRIM([name]))", row, {}) == 11
    assert evaluate("ISNULL([missing])", row, {}) is True


def test_variables_and_casts():
    assert evaluate("(DT_I8)@[User::BatchId]", {}, {"BatchId": "42"}) == 42
    assert evaluate("(DT_STR,10)[n]", {"n": 5}, {}) == "5"


def test_invalid_cast_raises():
    with pytest.raises(CastError):
        evaluate("(DT_I4)[qty]", {"qty": "abc"}, {})
    with pytest.raises(CastError):
        evaluate("(DT_DATE)[d]", {"d": "2020-13-45"}, {})


def test_short_circuit_protects_cast():
    # the second half would raise on a non-numeric slice; || must short-circuit.
    expr = '(LEN([sku]) <> 6) || ((DT_I4)SUBSTRING([sku],2,5) < 1)'
    assert evaluate(expr, {"sku": "SKU-UNKNOWN"}, {}) is True
    assert evaluate(expr, {"sku": "P99999"}, {}) is False


def test_row_hash_is_deterministic_and_sensitive():
    a = evaluate("ROW_HASH([a], [b])", {"a": "x", "b": "y"}, {})
    b = evaluate("ROW_HASH([a], [b])", {"a": "x", "b": "y"}, {})
    c = evaluate("ROW_HASH([a], [b])", {"a": "x", "b": "z"}, {})
    assert a == b != c and len(a) == 64


# --- parser (unit, against the real package files) -----------------------
def test_parse_load_stores():
    package = parse_package(PACKAGES / "LoadStores.dtsx")
    assert package.name == "LoadStores"
    widths = {c.name: c.width for c in package.connections["StoresFlatFile"].columns}
    assert widths == {
        "store_code": 6,
        "store_name": 40,
        "region": 12,
        "country": 3,
        "open_date_raw": 10,
    }
    flow = package.executables[0].pipeline
    classes = {c.class_id for c in flow.components}
    assert "Microsoft.FlatFileSource" in classes
    assert "Microsoft.Lookup" in classes
    assert "Microsoft.ConditionalSplit" in classes
    assert "Microsoft.OleDbDestination" in classes
    assert any(p.start_output == "Error" for p in flow.paths)


def test_parse_sales_foreach_and_fact_precedence():
    sales = parse_package(PACKAGES / "LoadSalesCsv.dtsx")
    loop = sales.executables[0]
    assert loop.exec_type == "Microsoft.ForEachLoop"
    assert loop.properties["FileSpec"] == "sales_*.csv"
    assert loop.children[0].pipeline.components

    fact = parse_package(PACKAGES / "LoadFactSales.dtsx")
    names = [e.name for e in fact.executables]
    assert names[0] == "Load Fact Sales"
    assert len(fact.executables[0].constraints) == 1


# --- integration ----------------------------------------------------------
def _reset_failed_rows(batch_id):
    with db.get_connection() as conn:
        db.execute(conn, "DELETE FROM audit.failed_rows WHERE batch_id=%s", (batch_id,))


@pytest.mark.integration
def test_load_stores_redirects_exactly_three_rows():
    batch_id = 900001
    _reset_failed_rows(batch_id)
    result = execute_package(
        PACKAGES / "LoadStores.dtsx",
        {"BatchId": batch_id, "LandingPath": "data/landing/"},
    )
    assert result.status == "SUCCESS", result.error
    assert result.rows_read == 203
    assert result.rows_inserted == 200
    assert result.rows_rejected == 3

    with db.get_connection() as conn:
        failed = db.scalar(
            conn,
            "SELECT COUNT(*) FROM audit.failed_rows WHERE batch_id=%s",
            (batch_id,),
        )
        staged = db.scalar(
            conn,
            "SELECT COUNT(*) FROM stg.stores_raw WHERE batch_id=%s AND is_valid=1",
            (batch_id,),
        )
    assert failed == 3
    assert staged == 200


@pytest.mark.integration
def test_load_sales_rejects_every_injected_bad_row(tmp_path):
    files = sorted(LANDING.glob("sales_*.csv"))[:3]
    assert files, "run `make seed` first"
    for src in files:
        shutil.copy(src, tmp_path / src.name)

    expected_bad = 0
    expected_good = 0
    for src in files:
        with src.open() as fh:
            for row in csv.DictReader(fh):
                sku = row["sku"]
                sku_ok = (
                    len(sku) == 6
                    and sku[0] == "P"
                    and sku[1:].isdigit()
                    and 1 <= int(sku[1:]) <= 5000
                )
                try:
                    int(row["qty"])
                    qty_ok = True
                except ValueError:
                    qty_ok = False
                try:
                    price_ok = float(row["unit_price"]) >= 0
                except ValueError:
                    price_ok = False
                if sku_ok and qty_ok and price_ok:
                    expected_good += 1
                else:
                    expected_bad += 1

    batch_id = 900002
    _reset_failed_rows(batch_id)
    result = execute_package(
        PACKAGES / "LoadSalesCsv.dtsx",
        {"BatchId": batch_id, "LandingPath": str(tmp_path) + "/"},
    )
    assert result.status == "SUCCESS", result.error
    assert result.rows_read == len(files) * 8000
    assert result.rows_rejected == expected_bad
    assert result.rows_inserted == expected_good

    with db.get_connection() as conn:
        staged = db.scalar(
            conn,
            "SELECT COUNT(*) FROM stg.sales_raw WHERE batch_id=%s",
            (batch_id,),
        )
    assert staged == expected_good
