"""Parser for the SSIS ``.dtsx`` package format used by this project.

The packages are real DTS:Executable XML documents.  This parser extracts the
pieces the runtime needs: connection managers, variables, package parameters,
executables (Data Flow / Execute SQL / ForEach Loop), precedence constraints and
the pipeline graph (components, outputs, paths and error outputs).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path as FsPath

DTS_NS = "www.microsoft.com/SqlServer/Dts"

__all__ = [
    "parse_package",
    "Package",
    "Executable",
    "Pipeline",
    "Component",
    "Output",
    "Path",
    "ConnectionManager",
]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str) -> str | None:
    if el is None:
        return None
    value = el.get(name)
    if value is not None:
        return value
    for key, val in el.attrib.items():
        if _local(key) == name:
            return val
    return None


def _props(el: ET.Element) -> dict[str, str]:
    props: dict[str, str] = {}
    for child in el:
        if _local(child.tag) == "Property":
            name = _attr(child, "Name")
            if name is not None:
                props[name] = (child.text or "").strip()
    return props


@dataclass
class FlatFileColumn:
    name: str
    width: int | None = None
    data_type: str = "string"


@dataclass
class ConnectionManager:
    ref_id: str
    name: str
    creation_name: str
    properties: dict[str, str] = field(default_factory=dict)
    columns: list[FlatFileColumn] = field(default_factory=list)


@dataclass
class Output:
    ref_id: str
    name: str
    is_error: bool = False
    columns: list[str] = field(default_factory=list)


@dataclass
class Component:
    ref_id: str
    name: str
    class_id: str
    connection_manager: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Output] = field(default_factory=dict)
    derived_columns: list[tuple[str, str]] = field(default_factory=list)
    join_columns: list[tuple[str, str]] = field(default_factory=list)
    cases: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Path:
    ref_id: str
    start: str
    end: str
    start_output: str
    end_input: str


@dataclass
class Pipeline:
    components: list[Component] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)


@dataclass
class Executable:
    ref_id: str
    name: str
    exec_type: str
    properties: dict[str, str] = field(default_factory=dict)
    children: list["Executable"] = field(default_factory=list)
    constraints: list[tuple[str, str]] = field(default_factory=list)
    pipeline: Pipeline | None = None


@dataclass
class Package:
    name: str
    path: str
    parameters: dict[str, str] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)
    connections: dict[str, ConnectionManager] = field(default_factory=dict)
    executables: list[Executable] = field(default_factory=list)


def _iter_tag(el: ET.Element, wrapper: str, item: str):
    for child in el:
        tag = _local(child.tag)
        if tag == wrapper:
            for sub in child:
                if _local(sub.tag) == item:
                    yield sub
        elif tag == item:
            yield child


def _parse_pipeline(el: ET.Element) -> Pipeline:
    pipeline = Pipeline()
    for comp_el in _iter_tag(el, "components", "component"):
        comp = Component(
            ref_id=_attr(comp_el, "refId") or "",
            name=_attr(comp_el, "name") or "",
            class_id=_attr(comp_el, "componentClassID") or "",
            connection_manager=_attr(comp_el, "connectionManager"),
        )
        for child in comp_el:
            tag = _local(child.tag)
            if tag == "properties":
                for prop in child:
                    if _local(prop.tag) == "property":
                        comp.properties[_attr(prop, "name") or ""] = (prop.text or "").strip()
            elif tag == "outputs":
                for out_el in child:
                    if _local(out_el.tag) != "output":
                        continue
                    output = Output(
                        ref_id=_attr(out_el, "refId") or "",
                        name=_attr(out_el, "name") or "",
                        is_error=(_attr(out_el, "isErrorOutput") or "").lower() == "true",
                    )
                    for sub in out_el:
                        if _local(sub.tag) == "columns":
                            for col in sub:
                                if _local(col.tag) == "column":
                                    output.columns.append(_attr(col, "name") or "")
                    comp.outputs[output.name] = output
            elif tag == "derivedColumns":
                for dc in child:
                    if _local(dc.tag) == "derivedColumn":
                        comp.derived_columns.append(
                            (_attr(dc, "name") or "", _attr(dc, "expression") or "")
                        )
            elif tag == "joinColumns":
                for jc in child:
                    if _local(jc.tag) == "joinColumn":
                        comp.join_columns.append(
                            (_attr(jc, "left") or "", _attr(jc, "right") or "")
                        )
            elif tag == "cases":
                for case in child:
                    if _local(case.tag) == "case":
                        comp.cases.append(
                            (_attr(case, "name") or "", _attr(case, "expression") or "")
                        )
        pipeline.components.append(comp)
    for path_el in _iter_tag(el, "paths", "path"):
        pipeline.paths.append(
            Path(
                ref_id=_attr(path_el, "refId") or "",
                start=_attr(path_el, "start") or "",
                end=_attr(path_el, "end") or "",
                start_output=_attr(path_el, "startOutput") or "Output",
                end_input=_attr(path_el, "endInput") or "Input",
            )
        )
    return pipeline


def _parse_executable(el: ET.Element, constraints: list[tuple[str, str]]) -> Executable:
    exe = Executable(
        ref_id=_attr(el, "refId") or "",
        name=_attr(el, "ObjectName") or "",
        exec_type=_attr(el, "ExecutableType") or "",
        properties=_props(el),
        constraints=constraints,
    )
    for child in el:
        tag = _local(child.tag)
        if tag == "Executables":
            for sub in child:
                if _local(sub.tag) == "Executable":
                    exe.children.append(_parse_executable(sub, []))
        elif tag == "ObjectData":
            for sub in child:
                if _local(sub.tag) == "Pipeline":
                    exe.pipeline = _parse_pipeline(sub)
    return exe


def parse_package(path: str | FsPath) -> Package:
    path = FsPath(path)
    root = ET.parse(path).getroot()
    if _local(root.tag) != "Executable":
        raise ValueError(f"{path} is not a DTS:Executable package")

    package = Package(name=_attr(root, "ObjectName") or path.stem, path=str(path))

    for child in root:
        tag = _local(child.tag)
        if tag == "PackageParameters":
            for p in child:
                if _local(p.tag) == "PackageParameter":
                    name = _attr(p, "ObjectName") or ""
                    props = _props(p)
                    package.parameters[name] = props.get("Value", "")
        elif tag == "Variables":
            for v in child:
                if _local(v.tag) == "Variable":
                    name = _attr(v, "ObjectName") or ""
                    props = _props(v)
                    package.variables[name] = props.get("Value", "")
        elif tag == "ConnectionManagers":
            for cm_el in child:
                if _local(cm_el.tag) != "ConnectionManager":
                    continue
                cm = ConnectionManager(
                    ref_id=_attr(cm_el, "refId") or "",
                    name=_attr(cm_el, "ObjectName") or "",
                    creation_name=_attr(cm_el, "CreationName") or "",
                    properties=_props(cm_el),
                )
                for sub in cm_el:
                    if _local(sub.tag) == "FlatFileColumns":
                        for col in sub:
                            if _local(col.tag) == "FlatFileColumn":
                                width = _attr(col, "Width")
                                cm.columns.append(
                                    FlatFileColumn(
                                        name=_attr(col, "ObjectName") or "",
                                        width=int(width) if width else None,
                                        data_type=_attr(col, "DataType") or "string",
                                    )
                                )
                package.connections[cm.name] = cm
        elif tag == "Executables":
            for sub in child:
                if _local(sub.tag) == "Executable":
                    package.executables.append(_parse_executable(sub, []))
        elif tag == "PrecedenceConstraints":
            for pc in child:
                if _local(pc.tag) != "PrecedenceConstraint":
                    continue
                frm = _attr(pc, "From")
                to = _attr(pc, "To")
                if frm and to:
                    for exe in package.executables:
                        if exe.ref_id == frm:
                            exe.constraints.append((frm, to))
    return package
