"""Deterministic checks for the multi-source extract generator."""

from __future__ import annotations

import json

import gen_sources


def test_generate_deterministic_counts(tmp_path):
    manifest = gen_sources.generate(tmp_path)

    assert manifest["seed"] == 42
    assert manifest["business_days"] == 90
    assert manifest["n_stores"] == 200
    assert manifest["n_products"] == 5000
    assert manifest["rows_per_day"] == 8000

    stores = manifest["stores"]
    assert stores["valid_rows"] == 200
    assert stores["malformed_rows"] == 3
    assert stores["total_rows"] == 203
    assert stores["record_width"] == 71

    sales = manifest["sales"]
    assert sales["files"] == 90
    assert sales["rows"] == 720000
    assert sales["bad_rows"] == 2880
    assert sales["bad_by_type"] == {"qty": 960, "sku": 960, "price": 960}

    products = manifest["products"]
    assert products["products"] == 5000
    assert products["pages"] == 10
    assert products["page_size"] == 500

    assert manifest["product_changes"]["changes"] == 120


def test_generated_files_present(tmp_path):
    gen_sources.generate(tmp_path)
    expected = [
        "stores.txt",
        "manifest.json",
        "product_changes.json",
        "sales_20240101.csv",
        "sales_20240503.csv",
        "products_page_001.json",
        "products_page_010.json",
    ]
    for name in expected:
        assert (tmp_path / name).exists(), f"missing {name}"


def test_stores_fixed_width_and_malformed(tmp_path):
    gen_sources.generate(tmp_path)
    lines = (tmp_path / "stores.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 203

    widths = gen_sources.STORE_FIELD_WIDTHS
    region_start = widths["store_code"] + widths["store_name"]
    valid_line = lines[0]
    assert len(valid_line) == gen_sources.STORE_RECORD_WIDTH
    region = valid_line[region_start : region_start + widths["region"]].strip()
    assert region in gen_sources.REGIONS

    malformed = lines[-3:]
    # bad date row is still the declared width but keeps the bad token
    assert len(malformed[0]) == gen_sources.STORE_RECORD_WIDTH
    assert "2020-13-45" in malformed[0]
    # missing-region row has a blank region slice
    missing = malformed[1]
    region_slice = missing[region_start : region_start + widths["region"]]
    assert region_slice.strip() == ""
    # over-long name row exceeds the declared record width
    assert len(malformed[2]) > gen_sources.STORE_RECORD_WIDTH


def test_determinism_byte_identical(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    gen_sources.generate(first)
    gen_sources.generate(second)
    assert (first / "stores.txt").read_bytes() == (second / "stores.txt").read_bytes()
    assert (first / "sales_20240101.csv").read_bytes() == (
        second / "sales_20240101.csv"
    ).read_bytes()
    assert json.loads((first / "manifest.json").read_text()) == json.loads(
        (second / "manifest.json").read_text()
    )
