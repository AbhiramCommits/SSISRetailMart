"""Package execution engine (the ``dtexec`` equivalent).

``execute_package`` parses a ``.dtsx`` file, honours precedence constraints,
runs Data Flow / Execute SQL / ForEach Loop executables, routes rejected rows to
the configured error output, writes ``audit.etl_batch`` bookkeeping and returns a
:class:`PackageResult`.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import db
from .components import Context, build_component
from .dtsx_parser import Executable, Pipeline, parse_package
from .expressions import evaluate

REPO_ROOT = Path(__file__).resolve().parents[1]

__all__ = ["execute_package", "PackageResult", "run_pipeline"]


@dataclass
class PackageResult:
    package: str
    batch_id: int
    status: str
    rows_read: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_rejected: int = 0
    duration_ms: int = 0
    error: str | None = None
    detail: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "SUCCESS" else 1

    def to_dict(self) -> dict:
        data = asdict(self)
        data["exit_code"] = self.exit_code
        return data


def execute_package(path: str | Path, params: dict | None = None, root: str | Path | None = None) -> PackageResult:
    package = parse_package(path)
    variables: dict = {}
    variables.update(package.parameters)
    variables.update(package.variables)
    variables.setdefault("LandingPath", "data/landing/")
    if params:
        variables.update({k: v for k, v in params.items() if v is not None})

    batch_id = int(variables.get("BatchId") or 0)
    ctx = Context(
        package_name=package.name,
        batch_id=batch_id,
        variables=variables,
        connections=package.connections,
        root=Path(root) if root else REPO_ROOT,
    )

    started = time.time()
    status = "SUCCESS"
    error: str | None = None
    _audit_start(ctx)
    try:
        for executable in _order_executables(package.executables):
            _run_executable(executable, ctx)
    except Exception as exc:  # noqa: BLE001 - surfaced as a failed package result
        status = "FAILED"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        _audit_end(ctx, status)

    duration_ms = int((time.time() - started) * 1000)
    result = PackageResult(
        package=package.name,
        batch_id=batch_id,
        status=status,
        rows_read=ctx.stats["rows_read"],
        rows_inserted=ctx.stats["rows_inserted"],
        rows_updated=ctx.stats["rows_updated"],
        rows_rejected=ctx.stats["rows_rejected"],
        duration_ms=duration_ms,
        error=error,
        detail={"variables": variables},
    )
    return result


# executable dispatch -----------------------------------------------------
def _run_executable(executable: Executable, ctx: Context) -> None:
    etype = executable.exec_type
    if etype == "Microsoft.Pipeline":
        if executable.pipeline is None:
            raise ValueError(f"pipeline executable {executable.name!r} has no graph")
        run_pipeline(executable.pipeline, ctx)
    elif etype == "Microsoft.ExecuteSQLTask":
        _run_sql_task(executable, ctx)
    elif etype == "Microsoft.ForEachLoop":
        _run_foreach(executable, ctx)
    else:
        raise ValueError(f"unsupported executable type {etype!r}")


def run_pipeline(pipeline: Pipeline, ctx: Context) -> None:
    components = {c.ref_id: build_component(c) for c in pipeline.components}
    buffers: dict[tuple[str, str], list[dict]] = {}
    for component_id in _topological_order(
        [c.ref_id for c in pipeline.components],
        [(p.start, p.end) for p in pipeline.paths],
    ):
        incoming: list[dict] = []
        for path in pipeline.paths:
            if path.end == component_id:
                incoming.extend(buffers.pop((path.end, path.end_input), []))
        outputs = components[component_id].execute(incoming, ctx)
        for path in pipeline.paths:
            if path.start == component_id:
                rows = outputs.get(path.start_output)
                if rows:
                    buffers.setdefault((path.end, path.end_input), []).extend(rows)


def _run_sql_task(executable: Executable, ctx: Context) -> None:
    sql = executable.properties.get("SqlStatement", "")
    statement = _substitute_variables(sql, ctx.variables)
    with db.get_connection() as conn:
        result_rows = db.query_dicts(conn, statement)
    for record in result_rows:
        if "rows_inserted" in record:
            ctx.stats["rows_inserted"] += int(record["rows_inserted"] or 0)
        if "rows_updated" in record:
            ctx.stats["rows_updated"] += int(record["rows_updated"] or 0)
        if "rows_affected" in record:
            ctx.stats["rows_inserted"] += int(record["rows_affected"] or 0)


def _run_foreach(executable: Executable, ctx: Context) -> None:
    props = executable.properties
    directory_expr = props.get("DirectoryExpression", "")
    directory = (
        str(evaluate(directory_expr, {}, ctx.variables))
        if directory_expr
        else props.get("Directory", "")
    )
    file_spec = props.get("FileSpec", "*")
    variable_name = props.get("VariableName", "User::CurrentFile")
    variable_key = variable_name.split("::")[-1]
    directory_path = ctx.resolve_path(directory)
    for file in sorted(directory_path.glob(file_spec)):
        ctx.variables[variable_key] = str(file)
        for child in _order_executables(executable.children):
            _run_executable(child, ctx)


# auditing ----------------------------------------------------------------
def _audit_start(ctx: Context) -> None:
    if not ctx.batch_id:
        return
    with db.get_connection() as conn:
        db.execute(
            conn,
            "EXEC audit.sp_start_batch @batch_id=%s, @package_name=%s",
            (ctx.batch_id, ctx.package_name),
        )


def _audit_end(ctx: Context, status: str) -> None:
    if not ctx.batch_id:
        return
    with db.get_connection() as conn:
        db.execute(
            conn,
            "EXEC audit.sp_end_batch @batch_id=%s, @package_name=%s, @status=%s, "
            "@rows_read=%s, @rows_inserted=%s, @rows_updated=%s, @rows_rejected=%s",
            (
                ctx.batch_id,
                ctx.package_name,
                status,
                ctx.stats["rows_read"],
                ctx.stats["rows_inserted"],
                ctx.stats["rows_updated"],
                ctx.stats["rows_rejected"],
            ),
        )


# helpers -----------------------------------------------------------------
def _substitute_variables(sql: str, variables: dict) -> str:
    import re

    def repl(match):
        name = match.group(1).split("::")[-1]
        value = variables.get(name)
        if value is None:
            return "NULL"
        text = str(value)
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return text
        return "N'" + text.replace("'", "''") + "'"

    return re.sub(r"@\[([^\]]+)\]", repl, sql)


def _topological_order(nodes: list[str], edges: list[tuple[str, str]]) -> list[str]:
    incoming = {n: 0 for n in nodes}
    adjacency: dict[str, list[str]] = {n: [] for n in nodes}
    for src, dst in edges:
        if src not in incoming or dst not in incoming:
            continue
        adjacency[src].append(dst)
        incoming[dst] += 1
    queue = [n for n in nodes if incoming[n] == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt in adjacency[node]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(nodes):
        raise ValueError("pipeline contains a cycle")
    return order


def _order_executables(executables: list[Executable]) -> list[Executable]:
    by_id = {e.ref_id: e for e in executables}
    nodes = [e.ref_id for e in executables]
    edges: list[tuple[str, str]] = []
    for executable in executables:
        for frm, to in executable.constraints:
            if frm in by_id and to in by_id:
                edges.append((frm, to))
    if edges:
        order = _topological_order(nodes, edges)
        return [by_id[i] for i in order]
    return list(executables)
