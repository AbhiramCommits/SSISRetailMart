"""Thin pymssql wrapper shared by the runtime, scripts and tests.

Connection settings come from the environment (``.env`` supported).  All helpers
open short-lived connections so the runtime stays stateless between packages.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from pathlib import Path

import pymssql
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DATABASE = os.getenv("MSSQL_DATABASE", "RetailMart")

_GO_RE = re.compile(r"^\s*GO\s*(--.*)?$", re.IGNORECASE)


def connection_kwargs(database: str | None = None) -> dict:
    return {
        "server": os.getenv("MSSQL_HOST", "127.0.0.1"),
        "port": str(os.getenv("MSSQL_PORT", "11433")),
        "user": os.getenv("MSSQL_USER", "sa"),
        "password": os.getenv("SA_PASSWORD", "Str0ng!Passw0rd"),
        "database": database or DEFAULT_DATABASE,
        "login_timeout": int(os.getenv("MSSQL_LOGIN_TIMEOUT", "15")),
        "timeout": int(os.getenv("MSSQL_QUERY_TIMEOUT", "600")),
        "autocommit": True,
    }


def connect(database: str | None = None):
    return pymssql.connect(**connection_kwargs(database))


@contextmanager
def get_connection(database: str | None = None):
    conn = connect(database)
    try:
        yield conn
    finally:
        conn.close()


def split_batches(script: str) -> list[str]:
    """Split a T-SQL script on standalone ``GO`` batch separators."""
    batches: list[str] = []
    current: list[str] = []
    for line in script.splitlines():
        if _GO_RE.match(line):
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    tail = "\n".join(current).strip()
    if tail:
        batches.append(tail)
    return batches


def execute_script(conn, script: str) -> None:
    cursor = conn.cursor()
    try:
        for batch in split_batches(script):
            cursor.execute(batch)
    finally:
        cursor.close()


def execute_file(conn, path: str | Path) -> None:
    execute_script(conn, Path(path).read_text(encoding="utf-8"))


def query(conn, sql: str, params: Sequence | None = None) -> list[tuple]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params) if params else None)
        if cursor.description is None:
            return []
        return cursor.fetchall()
    finally:
        cursor.close()


def query_dicts(conn, sql: str, params: Sequence | None = None) -> list[dict]:
    cursor = conn.cursor(as_dict=True)
    try:
        cursor.execute(sql, tuple(params) if params else None)
        if cursor.description is None:
            return []
        return list(cursor.fetchall())
    finally:
        cursor.close()


def scalar(conn, sql: str, params: Sequence | None = None):
    rows = query(conn, sql, params)
    return rows[0][0] if rows else None


def execute(conn, sql: str, params: Sequence | None = None) -> int:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, tuple(params) if params else None)
        return cursor.rowcount
    finally:
        cursor.close()


def executemany(conn, sql: str, rows: Iterable[Sequence]) -> int:
    cursor = conn.cursor()
    try:
        cursor.executemany(sql, [tuple(r) for r in rows])
        return cursor.rowcount
    finally:
        cursor.close()


def quote_ident(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"
