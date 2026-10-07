"""Shared conversion contracts and source-file helpers."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from mvp.scripts.readers import read_table, to_datetime_text, to_num
from mvp.standard_schema import SHEET_COLUMNS, STANDARD_SHEETS
from mvp.standard_workbook import write_standard_workbook_fast


@dataclass(frozen=True)
class ConversionRequest:
    platform: str
    dealer_name: str
    source_paths: Mapping[str, Sequence[Path]]
    activity_inputs: Sequence[Mapping[str, Any]]
    coupon_inputs: Sequence[Mapping[str, Any]]
    output_dir: Path
    coverage_start: str = ""
    coverage_end: str = ""


@dataclass(frozen=True)
class ConversionResult:
    workbook_path: Path
    sources_zip_path: Path
    report_path: Path
    counts: Mapping[str, int]


def source_rows(path: Path, header_row: int = 1) -> tuple[list[str], list[list[str]]]:
    _, _, header, rows = read_table(str(path), header_row=header_row)
    return header, rows


def index_header(header: Sequence[str]) -> dict[str, int]:
    return {str(value).strip(): index for index, value in enumerate(header) if str(value).strip()}


def value(row: Sequence[Any], indexes: Mapping[str, int], *names: str) -> str:
    for name in names:
        index = indexes.get(name)
        if index is not None and index < len(row):
            return "" if row[index] is None else str(row[index]).strip()
    return ""


def date_value(raw: str) -> str:
    return to_datetime_text(raw) if raw else ""


def number_value(raw: str) -> str:
    number = to_num(raw)
    return "" if number is None else (str(int(number)) if float(number).is_integer() else str(number))


def empty_tables() -> dict[str, list[dict[str, str]]]:
    return {sheet: [] for sheet in STANDARD_SHEETS[1:]}


def build_sources_archive(source_paths: Sequence[Path], destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in source_paths:
            archive.write(path, arcname=path.name)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return digest


def add_activity_inputs(tables: dict[str, list[dict[str, str]]], inputs: Sequence[Mapping[str, Any]]) -> None:
    for item in inputs:
        activity = {column: str(item.get(column, "") or "") for column in SHEET_COLUMNS["标准活动"]}
        tables["标准活动"].append(activity)
        for rule in item.get("规则", ()):
            tables["标准活动规则"].append({column: str(rule.get(column, "") or "") for column in SHEET_COLUMNS["标准活动规则"]})
        for benefit in item.get("权益", ()):
            tables["标准活动权益"].append({column: str(benefit.get(column, "") or "") for column in SHEET_COLUMNS["标准活动权益"]})
        for scope in item.get("范围", ()):
            tables["标准活动范围"].append({column: str(scope.get(column, "") or "") for column in SHEET_COLUMNS["标准活动范围"]})


def add_coupon_inputs(tables: dict[str, list[dict[str, str]]], inputs: Sequence[Mapping[str, Any]]) -> None:
    for item in inputs:
        for sheet in ("标准优惠券配置", "标准优惠券发放规则", "标准优惠券使用规则"):
            tables[sheet].append({column: str(item.get(column, "") or "") for column in SHEET_COLUMNS[sheet]})
        for scope in item.get("范围", ()):
            tables["标准优惠券适用范围"].append({column: str(scope.get(column, "") or "") for column in SHEET_COLUMNS["标准优惠券适用范围"]})


def finish_conversion(request: ConversionRequest, tables: dict[str, list[dict[str, str]]], report_lines: Sequence[str]) -> ConversionResult:
    request.output_dir.mkdir(parents=True, exist_ok=True)
    source_files = [path for paths in request.source_paths.values() for path in paths]
    archive_path = request.output_dir / "sources.zip"
    archive_hash = build_sources_archive(source_files, archive_path)
    order_dates = sorted(str(row.get("下单时间", ""))[:10] for row in tables.get("标准订单明细", ()) if row.get("下单时间"))
    manifest = {
        "模板版本": "v1",
        "转换工具版本": "v1",
        "经销商名称": request.dealer_name,
        "平台名称": request.platform,
        "数据开始日期": request.coverage_start or (order_dates[0] if order_dates else ""),
        "数据结束日期": request.coverage_end or (order_dates[-1] if order_dates else ""),
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    workbook_path = request.output_dir / "standard.xlsx"
    write_standard_workbook_fast(workbook_path, tables, manifest)
    report_path = request.output_dir / "conversion_report.txt"
    report_path.write_text("\n".join([*report_lines, f"sources_sha256={archive_hash}"]), encoding="utf-8")
    counts = {sheet: len(rows) for sheet, rows in tables.items()}
    return ConversionResult(workbook_path, archive_path, report_path, counts)
