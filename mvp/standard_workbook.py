"""Read and write the fixed standard Excel workbook."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from openpyxl import Workbook, load_workbook

from .standard_schema import SHEET_COLUMNS, STANDARD_SHEETS


@dataclass(frozen=True)
class StandardWorkbook:
    tables: dict[str, list[dict[str, str]]]
    manifest: dict[str, str]


def write_standard_workbook(
    path: Path,
    tables: Mapping[str, Sequence[Mapping[str, object]]],
    manifest: Mapping[str, object],
) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet in STANDARD_SHEETS:
        worksheet = workbook.create_sheet(sheet)
        columns = SHEET_COLUMNS[sheet]
        worksheet.append(list(columns))
        records = manifest if sheet == "导入清单" else tables.get(sheet, ())
        if sheet == "导入清单":
            records = [manifest]
        for record in records:
            worksheet.append(["" if record.get(column) is None else str(record.get(column)) for column in columns])
        for row in worksheet.iter_rows():
            for cell in row:
                cell.number_format = "@"
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def write_standard_workbook_fast(
    path: Path,
    tables: Mapping[str, Sequence[Mapping[str, object]]],
    manifest: Mapping[str, object],
) -> None:
    """Stream a large standard workbook. Values stay text so long identifiers round-trip."""
    workbook = Workbook(write_only=True)
    for sheet in STANDARD_SHEETS:
        worksheet = workbook.create_sheet(sheet)
        columns = list(SHEET_COLUMNS[sheet])
        worksheet.append(columns)
        records = [manifest] if sheet == "导入清单" else tables.get(sheet, ())
        for record in records:
            worksheet.append(["" if record.get(column) is None else str(record.get(column)) for column in columns])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def read_standard_workbook(path: Path) -> StandardWorkbook:
    workbook = load_workbook(path, read_only=True, data_only=True)
    if tuple(workbook.sheetnames) != STANDARD_SHEETS:
        raise ValueError("工作表必须按固定标准模板存在且顺序一致")
    tables: dict[str, list[dict[str, str]]] = {}
    manifest: dict[str, str] = {}
    for sheet in STANDARD_SHEETS:
        worksheet = workbook[sheet]
        rows = worksheet.iter_rows(values_only=True)
        header = tuple("" if value is None else str(value) for value in next(rows))
        if header != SHEET_COLUMNS[sheet]:
            raise ValueError(f"{sheet} 表头不符合标准模板")
        records = []
        for values in rows:
            record = {column: "" if value is None else str(value) for column, value in zip(header, values)}
            if any(value.strip() for value in record.values()):
                records.append(record)
        if sheet == "导入清单":
            if len(records) != 1:
                raise ValueError("导入清单必须恰好一行")
            manifest = records[0]
        else:
            tables[sheet] = records
    workbook.close()
    return StandardWorkbook(tables=tables, manifest=manifest)
