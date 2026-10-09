"""Run all five SSIS packages in order through the dtexec-compatible CLI."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ssis_runtime.engine import execute_package  # noqa: E402

PACKAGES = [
    "LoadStores",
    "LoadSalesCsv",
    "LoadProductsRest",
    "LoadDimensions",
    "LoadFactSales",
]

RESULTS_DIR = ROOT / "results"


def run_all(batch_id: int | None = None, landing: str = "data/landing/") -> list[dict]:
    batch_id = batch_id or int(time.time())
    results: list[dict] = []
    for name in PACKAGES:
        package_path = ROOT / "ssis" / "packages" / f"{name}.dtsx"
        result = execute_package(package_path, {"BatchId": batch_id, "LandingPath": landing})
        results.append(result.to_dict())
        print(
            f"[{name}] status={result.status} read={result.rows_read} "
            f"inserted={result.rows_inserted} updated={result.rows_updated} "
            f"rejected={result.rows_rejected} duration_ms={result.duration_ms}"
        )
        if result.exit_code != 0:
            print(f"package {name} failed: {result.error}")
            break
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "etl_run.json").write_text(
        json.dumps({"batch_id": batch_id, "packages": results}, indent=2), encoding="utf-8"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", type=int, default=None)
    parser.add_argument("--landing", default="data/landing/")
    args = parser.parse_args()
    results = run_all(batch_id=args.batch_id, landing=args.landing)
    return 0 if all(r["status"] == "SUCCESS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
