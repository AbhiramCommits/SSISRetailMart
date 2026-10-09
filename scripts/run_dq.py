"""Run the data-quality assertions for a batch (default: the latest batch)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.airflow_tasks import run_assertions  # noqa: E402
from ssis_runtime import db  # noqa: E402


def latest_batch() -> int:
    with db.get_connection() as conn:
        return int(db.scalar(conn, "SELECT ISNULL(MAX(batch_id), 0) FROM audit.etl_batch") or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", type=int, default=None)
    args = parser.parse_args()
    batch_id = args.batch_id if args.batch_id is not None else latest_batch()
    rows = run_assertions(batch_id)
    failures = 0
    for row in rows:
        observed = row["observed_value"]
        threshold = row["threshold"]
        print(f"{row['status']:4} {row['assertion_name']:28} {observed} <= {threshold}")
        if row["status"] != "PASS":
            failures += 1
    print(f"batch {batch_id}: {len(rows) - failures}/{len(rows)} assertions passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
