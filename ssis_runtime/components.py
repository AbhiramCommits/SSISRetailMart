"""Pipeline component implementations for the dtexec-compatible runtime.

Each component consumes a list of row dicts, produces one list of row dicts per
named output, and reports statistics through the shared :class:`Context`.  Row
dicts may carry a ``__meta__`` key describing why a row was rejected; that
metadata is what the ``audit.failed_rows`` destination persists.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .dtsx_parser import Component
from .expressions import _truthy, evaluate

__all__ = [
    "Context",
    "build_component",
    "COMPONENT_TYPES",
    "SOURCE_TYPES",
    "DESTINATION_TYPES",
    "FAILED_ROWS_TABLE",
]

FAILED_ROWS_TABLE = "audit.failed_rows"


@dataclass
class Context:
    package_name: str
    batch_id: int
    variables: dict
    connections: dict
    root: Path
    stats: dict = field(
        default_factory=lambda: {
            "rows_read": 0,
            "rows_inserted": 0,
            "rows_rejected": 0,
            "rows_updated": 0,
        }
    )
    _column_cache: dict = field(default_factory=dict)

    def resolve_path(self, raw: str) -> Path:
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate
        relative = self.root / candidate
        return relative

    def connection_string(self, name: str) -> str:
        cm = self.connections[name]
        expr = cm.properties.get("ConnectionStringExpression")
        if expr:
            value = evaluate(expr, {}, self.variables)
            return "" if value is None else str(value)
        return cm.properties.get("ConnectionString", "")

    def target_columns(self, table: str) -> list[str]:
        key = table.lower()
        if key not in self._column_cache:
            schema, _, name = table.partition(".")
            with db.get_connection() as conn:
                rows = db.query(
                    conn,
                    "SELECT c.name FROM sys.columns c "
                    "JOIN sys.tables t ON t.object_id=c.object_id "
                    "JOIN sys.schemas s ON s.schema_id=t.schema_id "
                    "WHERE s.name=%s AND t.name=%s AND c.is_identity=0 "
                    "ORDER BY c.column_id",
                    (schema, name),
                )
            self._column_cache[key] = [r[0] for r in rows]
        return self._column_cache[key]


def make_error(row: dict, component: str, code: int, column: str, description: str, raw=None) -> dict:
    out = dict(row)
    out["__meta__"] = {
        "component": component,
        "error_code": code,
        "error_column": column,
        "error_description": description,
        "raw_row": raw if raw is not None else _raw_row(row),
    }
    return out


def _raw_row(row: dict) -> str:
    parts = [f"{k}={v}" for k, v in row.items() if not k.startswith("__")]
    return ", ".join(parts)[:4000]


class BaseComponent:
    class_id = ""

    def __init__(self, definition: Component):
        self.defn = definition

    def execute(self, input_rows: list[dict], ctx: Context) -> dict[str, list[dict]]:
        raise NotImplementedError


class FlatFileSource(BaseComponent):
    class_id = "Microsoft.FlatFileSource"

    def execute(self, input_rows, ctx):
        cm = ctx.connections[self.defn.connection_manager]
        raw = ctx.connection_string(self.defn.connection_manager)
        path = ctx.resolve_path(raw)
        delim = _decode(cm.properties.get("ColumnDelimiter", ","))
        fmt = cm.properties.get("Format", "Delimited")
        header = cm.properties.get("ColumnNamesInFirstDataRow", "False").lower() == "true"
        columns = [c.name for c in cm.columns]
        widths = [c.width for c in cm.columns]

        rows: list[dict] = []
        errors: list[dict] = []
        row_num = 0

        if fmt.lower() == "fixedwidth":
            expected = sum(w for w in widths if w)
            for line in _read_lines(path):
                row_num += 1
                if len(line) != expected:
                    errors.append(
                        make_error(
                            {},
                            self.defn.name,
                            1001,
                            columns[-1] if columns else "",
                            f"fixed-width record length {len(line)} != expected {expected}",
                            raw=line,
                        )
                    )
                    continue
                values: dict[str, object] = {}
                offset = 0
                for col, width in zip(columns, widths):
                    values[col] = line[offset : offset + width]
                    offset += width
                rows.append(values)
        else:
            with path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh, delimiter=delim.strip() or ",")
                for record in reader:
                    row_num += 1
                    if header and row_num == 1:
                        if not columns:
                            columns = [c.strip() for c in record]
                        continue
                    if len(record) != len(columns):
                        errors.append(
                            make_error(
                                {},
                                self.defn.name,
                                1002,
                                "",
                                f"expected {len(columns)} columns, found {len(record)}",
                                raw=delim.join(record),
                            )
                        )
                        continue
                    rows.append(dict(zip(columns, record)))

        for row in rows:
            row["source_file"] = path.name
            row["row_num"] = row_num
        for err in errors:
            err["source_file"] = path.name

        ctx.stats["rows_read"] += len(rows) + len(errors)
        return {"Output": rows, "Error": errors}


class JsonSource(BaseComponent):
    class_id = "Microsoft.JsonSource"

    def execute(self, input_rows, ctx):
        props = self.defn.properties
        root_key = props.get("jsonRoot", "items")
        default_effective = props.get("defaultEffectiveDate")
        use_live = props.get("useLiveApi", "false").lower() == "true"
        if use_live:
            items, source_name = _read_live_api(props, ctx)
            files = [source_name]
        else:
            pattern = props.get("pathExpression", "")
            raw = evaluate(pattern, {}, ctx.variables) if pattern else ""
            items = []
            files = []
            for path in sorted(ctx.root.glob(str(raw))):
                payload = json.loads(path.read_text(encoding="utf-8"))
                items.extend(_extract(payload, root_key))
                files.append(path.name)

        rows: list[dict] = []
        for idx, item in enumerate(items, start=1):
            row = dict(item)
            row.setdefault("effective_date", default_effective)
            row["source_file"] = files[0] if len(files) == 1 else f"{files[0]}+{len(files)-1}more"
            row["row_num"] = idx
            rows.append(row)
        ctx.stats["rows_read"] += len(rows)
        return {"Output": rows, "Error": []}


class DerivedColumn(BaseComponent):
    class_id = "Microsoft.DerivedColumn"

    def execute(self, input_rows, ctx):
        good: list[dict] = []
        errors: list[dict] = []
        for row in input_rows:
            work = dict(row)
            failed = None
            for name, expression in self.defn.derived_columns:
                try:
                    work[name] = evaluate(expression, work, ctx.variables)
                except Exception as exc:  # noqa: BLE001 - cast/eval failure routes row
                    failed = (name, exc)
                    break
            if failed is None:
                good.append(work)
            else:
                name, exc = failed
                errors.append(
                    make_error(
                        row,
                        self.defn.name,
                        2001,
                        name,
                        f"derived column {name} failed: {exc}",
                    )
                )
        return {"Output": good, "Error": errors}


_LOOKUP_CACHE: dict = {}


class Lookup(BaseComponent):
    class_id = "Microsoft.Lookup"

    def execute(self, input_rows, ctx):
        props = self.defn.properties
        sql = props.get("sqlCommand", "")
        cm_name = self.defn.connection_manager or props.get("connectionManager", "")
        cache_key = (cm_name, sql)
        if cache_key not in _LOOKUP_CACHE:
            with db.get_connection() as conn:
                result = db.query_dicts(conn, sql)
            index: dict[tuple, dict] = {}
            right_cols = {r for _, r in self.defn.join_columns}
            for record in result:
                key = tuple(record.get(c) for c in right_cols)
                index[key] = record
            _LOOKUP_CACHE[cache_key] = (index, right_cols)
        index, right_cols = _LOOKUP_CACHE[cache_key]

        matched: list[dict] = []
        unmatched: list[dict] = []
        for row in input_rows:
            key = tuple(row.get(left) for left, _ in self.defn.join_columns)
            record = index.get(key)
            if record is None:
                unmatched.append(row)
            else:
                merged = dict(row)
                for col, value in record.items():
                    merged.setdefault(col, value)
                matched.append(merged)
        return {"Output": matched, "NoMatch": unmatched}


class ConditionalSplit(BaseComponent):
    class_id = "Microsoft.ConditionalSplit"

    def execute(self, input_rows, ctx):
        reject_outputs = {
            o.strip() for o in self.defn.properties.get("rejectOutputs", "").split(",") if o.strip()
        }
        outputs: dict[str, list[dict]] = {name: [] for name, _ in self.defn.cases}
        outputs["Default"] = []
        for row in input_rows:
            routed = False
            for name, expression in self.defn.cases:
                if _truthy(evaluate(expression, row, ctx.variables)):
                    if name in reject_outputs:
                        outputs[name].append(
                            make_error(
                                row,
                                self.defn.name,
                                3001,
                                "",
                                f"row rejected by conditional split case {name}",
                            )
                        )
                    else:
                        outputs[name].append(row)
                    routed = True
                    break
            if not routed:
                outputs["Default"].append(row)
        return outputs


class OleDbDestination(BaseComponent):
    class_id = "Microsoft.OleDbDestination"

    def execute(self, input_rows, ctx):
        table = self.defn.properties.get("tableName", "")
        if table.lower() == FAILED_ROWS_TABLE:
            inserted = _write_failed_rows(input_rows, ctx)
            ctx.stats["rows_rejected"] += inserted
            return {"Output": []}
        inserted = _insert_rows(table, input_rows, ctx)
        ctx.stats["rows_inserted"] += inserted
        return {"Output": []}


class OleDbSource(BaseComponent):
    class_id = "Microsoft.OleDbSource"

    def execute(self, input_rows, ctx):
        sql = self.defn.properties.get("sqlCommand", "")
        with db.get_connection() as conn:
            rows = db.query_dicts(conn, sql)
        ctx.stats["rows_read"] += len(rows)
        return {"Output": rows, "Error": []}


def _write_failed_rows(rows, ctx):
    if not rows:
        return 0
    available = ctx.target_columns(FAILED_ROWS_TABLE)
    column_values: list[dict] = []
    for row in rows:
        meta = row.get("__meta__", {})
        values = {
            "batch_id": ctx.batch_id,
            "package_name": ctx.package_name,
            "component": meta.get("component", ctx.package_name),
            "error_code": meta.get("error_code"),
            "error_column": meta.get("error_column"),
            "raw_row": str(meta.get("raw_row", _raw_row(row)))[:4000],
            "error_description": meta.get("error_description", ""),
        }
        column_values.append({k: v for k, v in values.items() if k in available})
    columns = [c for c in available if any(c in v for v in column_values)]
    records = [tuple(v.get(c) for c in columns) for v in column_values]
    _bulk_insert(FAILED_ROWS_TABLE, columns, records)
    return len(records)


def _insert_rows(table, rows, ctx):
    if not rows:
        return 0
    available = ctx.target_columns(table)
    column_values: list[dict] = []
    for row in rows:
        values = {col: row[col] for col in available if col in row}
        if "batch_id" in available:
            values["batch_id"] = ctx.batch_id
        for extra in ("source_file", "row_num"):
            if extra in row and extra in available:
                values[extra] = row[extra]
        column_values.append(values)
    columns = [c for c in available if any(c in v for v in column_values)]
    prepared = [tuple(v.get(c) for c in columns) for v in column_values]
    _bulk_insert(table, columns, prepared)
    return len(prepared)


def _bulk_insert(table, columns, records, batch_size=500):
    if not records:
        return
    # SQL Server allows at most 2100 parameters per statement.
    batch_size = min(batch_size, max(1, 2000 // max(1, len(columns))))
    column_list = ", ".join(db.quote_ident(c) for c in columns)
    single = "(" + ", ".join(["%s"] * len(columns)) + ")"
    with db.get_connection() as conn:
        cursor = conn.cursor()
        try:
            for start in range(0, len(records), batch_size):
                chunk = records[start : start + batch_size]
                sql = f"INSERT INTO {table} ({column_list}) VALUES " + ", ".join(
                    [single] * len(chunk)
                )
                flat: list = []
                for record in chunk:
                    flat.extend(record)
                cursor.execute(sql, tuple(flat))
        finally:
            cursor.close()


def _read_lines(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip("\ufeff").strip() == "":
                continue
            yield line.rstrip("\n").rstrip("\r")


def _decode(value: str) -> str:
    if value in (r"\t", "\\t"):
        return "\t"
    return value


def _extract(payload, root_key):
    if isinstance(payload, list):
        return payload
    if root_key and isinstance(payload, dict) and root_key in payload:
        return payload[root_key]
    if isinstance(payload, dict) and "items" in payload:
        return payload["items"]
    return [payload]


def _read_live_api(props, ctx):
    import requests

    cm_name = props.get("connectionManager", "")
    base = ctx.connection_string(cm_name).rstrip("/") if cm_name in ctx.connections else ""
    api_path = props.get("apiPath", "/products?page=1")
    response = requests.get(base + api_path, timeout=10)
    response.raise_for_status()
    payload = response.json()
    return _extract(payload, props.get("jsonRoot", "items")), "live-api"


COMPONENT_TYPES = {
    FlatFileSource.class_id: FlatFileSource,
    JsonSource.class_id: JsonSource,
    DerivedColumn.class_id: DerivedColumn,
    Lookup.class_id: Lookup,
    ConditionalSplit.class_id: ConditionalSplit,
    OleDbDestination.class_id: OleDbDestination,
    OleDbSource.class_id: OleDbSource,
}

SOURCE_TYPES = {FlatFileSource.class_id, JsonSource.class_id, OleDbSource.class_id}
DESTINATION_TYPES = {OleDbDestination.class_id}


def build_component(definition: Component) -> BaseComponent:
    cls = COMPONENT_TYPES.get(definition.class_id)
    if cls is None:
        raise ValueError(f"unsupported componentClassID {definition.class_id!r}")
    return cls(definition)
