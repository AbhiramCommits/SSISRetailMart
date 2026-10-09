"""Block until SQL Server accepts connections, then report a live connection."""

from __future__ import annotations

import os
import sys
import time

import pymssql
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("MSSQL_HOST", "127.0.0.1")
PORT = int(os.getenv("MSSQL_PORT", "11433"))
USER = os.getenv("MSSQL_USER", "sa")
PASSWORD = os.getenv("SA_PASSWORD", "Str0ng!Passw0rd")
TIMEOUT_S = int(os.getenv("WAIT_FOR_SQL_TIMEOUT", "180"))


def try_connect():
    return pymssql.connect(
        server=HOST,
        port=str(PORT),
        user=USER,
        password=PASSWORD,
        database="master",
        login_timeout=5,
        timeout=5,
    )


def main() -> int:
    deadline = time.time() + TIMEOUT_S
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            conn = try_connect()
            with conn.cursor() as cur:
                cur.execute("SELECT @@VERSION AS v, DB_NAME() AS db")
                row = cur.fetchone()
            conn.close()
            version = row[0].splitlines()[0] if row else "unknown"
            print(
                f"live connection to SQL Server at {HOST}:{PORT} "
                f"(db={row[1]}): {version}"
            )
            return 0
        except Exception as exc:  # noqa: BLE001 - retry loop
            last_error = exc
            print(f"waiting for SQL Server at {HOST}:{PORT} ... {exc}")
            time.sleep(3)
    print(f"timed out after {TIMEOUT_S}s waiting for SQL Server: {last_error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
