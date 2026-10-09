"""Verify the DAX measures against real data via SQL <-> Python parity."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from powerbi.dax_parity import measures

ROOT = Path(__file__).resolve().parents[1]

CONTEXTS = [
    ("all-time", {}),
    ("single-month", {"year": 2024, "month": 2}),
    ("single-region", {"region": "West"}),
    ("yoy-window", {"year": 2024}),
]

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def warehouse():
    return measures.load_warehouse()


def _close(sql_value, py_value) -> bool:
    if sql_value is None and py_value is None:
        return True
    if sql_value is None or py_value is None:
        return False
    return abs(float(sql_value) - float(py_value)) <= 0.01


def test_measure_names_match_tmdl():
    text = (ROOT / "powerbi" / "measures.tmdl").read_text(encoding="utf-8")
    declared = set(re.findall(r"measure '([^']+)'", text))
    for name in measures.MEASURE_NAMES:
        assert name in declared, f"{name} missing from measures.tmdl"
    assert len(measures.MEASURE_NAMES) >= 14


@pytest.mark.parametrize("label,context", CONTEXTS)
def test_sql_matches_python_dax_semantics(label, context, warehouse):
    sql_values = measures.sql_measures(**context)
    py_values = measures.eval_measures(warehouse, **context)
    mismatches = {}
    for name in measures.MEASURE_NAMES:
        if not _close(sql_values.get(name), py_values.get(name)):
            mismatches[name] = (sql_values.get(name), py_values.get(name))
    assert not mismatches, f"{label} mismatches: {mismatches}"


def test_all_time_values_are_populated(warehouse):
    values = measures.eval_measures(warehouse, **{})
    assert values["Net Sales"] > 0
    assert values["Gross Sales"] >= values["Net Sales"] >= 0
    assert values["Units Sold"] > 0
    assert values["Active SKU Count"] == 5000
    assert 0 < values["Stockout Rate %"] < 1
    assert 0 < values["Rejected Row Rate %"] < 0.05
    assert values["Load Success Rate %"] == 1.0


def test_model_bim_structure():
    model = json.loads((ROOT / "powerbi" / "model.bim").read_text(encoding="utf-8"))
    tables = {t["name"] for t in model["model"]["tables"]}
    assert {
        "dim_date",
        "dim_product",
        "dim_store",
        "fact_sales",
        "fact_inventory_snapshot",
        "audit_load_health",
    } <= tables
    relationships = model["model"]["relationships"]
    assert len(relationships) == 6
    assert all(r["crossFilteringBehavior"] == "oneDirection" for r in relationships)
    date_table = next(t for t in model["model"]["tables"] if t["name"] == "dim_date")
    assert date_table["dataCategory"] == "Time"
    fact = next(t for t in model["model"]["tables"] if t["name"] == "fact_sales")
    hidden = {c["name"] for c in fact["columns"] if c.get("isHidden")}
    assert {"sale_sk", "product_sk", "store_sk"} <= hidden
