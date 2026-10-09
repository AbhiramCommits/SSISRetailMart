"""Idempotently apply every sql/ file to the container.

Order: sql/ddl/*.sql, then sql/procs/*.sql, then sql/checks/*.sql, then the
date dimension is populated once.  Use ``--reset`` to drop the database first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ssis_runtime import db  # noqa: E402

SQL_DIR = ROOT / "sql"
DATABASE = "RetailMart"


def _files(pattern: str) -> list[Path]:
    return sorted(SQL_DIR.glob(pattern))


def apply_all(reset: bool = False, verbose: bool = True) -> None:
    if reset:
        with db.get_connection("master") as conn:
            db.execute(conn, f"IF DB_ID('{DATABASE}') IS NOT NULL BEGIN ALTER DATABASE [{DATABASE}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{DATABASE}]; END")
        if verbose:
            print(f"dropped database {DATABASE}")

    with db.get_connection("master") as conn:
        for path in _files("ddl/01_*.sql"):
            if verbose:
                print(f"applying {path.relative_to(ROOT)}")
            db.execute_file(conn, path)
        # connection now has context RetailMart (USE inside 01_database.sql)
        for pattern in ("ddl/0[2-9]_*.sql", "procs/*.sql", "checks/*.sql"):
            for path in _files(pattern):
                if verbose:
                    print(f"applying {path.relative_to(ROOT)}")
                db.execute_file(conn, path)
        db.execute(conn, "EXEC dw.sp_populate_dim_date")
    if verbose:
        print("schema is up to date")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop the database first")
    args = parser.parse_args()
    apply_all(reset=args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
