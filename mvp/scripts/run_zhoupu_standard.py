# -*- coding: utf-8 -*-
"""把舟谱-羿柏试点转成标准工作簿，导入标准库并核算，再与 ec101_mvp.db 的结论对照。"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from converters.common import ConversionRequest
from converters.zhoupu_snapshot import COUPON_CONFIG, GIFT_ACTIVITY, convert_zhoupu_snapshot, pilot_source_paths
from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_workbook import read_standard_workbook

CALC_DATE = "2026-09-23"
REFERENCE = {
    "客户主数据": 2492,
    "商品主数据": 2655,
    "订单": 6697,
    "XD-only订单": 2644,
    "订单行": 76055,
    "履约": 6118,
    "券台账": 102,
    "已用券": 48,
    "返券归因订单": 45,
    "返券费用": 675.0,
    "满赠合格单": 142,
    "满赠应赠": 135,
    "满赠一致": 99,
    "满赠差异": 43,
    "实赠抱枕": 100.0,
    "释放候选": 179,
    "释放非候选": 8,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metrics(connection: sqlite3.Connection) -> dict[str, float]:
    def one(sql: str) -> float:
        value = connection.execute(sql).fetchone()[0]
        return 0 if value is None else value
    return {
        "客户主数据": one("SELECT COUNT(*) FROM customer WHERE customer_no NOT LIKE 'UNRESOLVED:%'"),
        "商品主数据": one("SELECT COUNT(*) FROM product WHERE product_no NOT LIKE 'UNMATCHED:%'"),
        "订单": one("SELECT COUNT(*) FROM order_header"),
        "XD-only订单": one("SELECT COUNT(*) FROM order_header WHERE order_source='XD履约(无SXD)'"),
        "订单行": one("SELECT COUNT(*) FROM order_line"),
        "履约": one("SELECT COUNT(*) FROM fulfillment"),
        "券台账": one("SELECT COUNT(*) FROM coupon_redemption"),
        "已用券": one("SELECT COUNT(*) FROM coupon_redemption WHERE status='已使用'"),
        "返券归因订单": one("SELECT COUNT(*) FROM coupon_redemption WHERE status='已使用' AND order_id IS NOT NULL"),
        "返券费用": one("SELECT coupon_benefit FROM calculation_run ORDER BY calculation_run_id DESC LIMIT 1"),
        "满赠合格单": one("SELECT COUNT(*) FROM entitlement_check WHERE gift_qty_entitled IS NOT NULL"),
        "满赠应赠": one("SELECT COALESCE(SUM(gift_qty_entitled),0) FROM activity_fee_summary"),
        "满赠一致": one("SELECT COUNT(*) FROM entitlement_check WHERE gift_qty_entitled IS NOT NULL AND consistency='一致'"),
        "满赠差异": one("SELECT COUNT(*) FROM entitlement_check WHERE gift_qty_entitled IS NOT NULL AND consistency='差异'"),
        "实赠抱枕": one("SELECT COALESCE(SUM(gift_qty_actual),0) FROM activity_fee_summary"),
        "释放候选": one("SELECT COUNT(*) FROM release_candidate WHERE is_candidate=1"),
        "释放非候选": one("SELECT COUNT(*) FROM release_candidate WHERE is_candidate=0"),
    }


def _write_report(path: Path, metrics: dict[str, float], conversion_report: str) -> int:
    lines = ["# 舟谱-羿柏标准链路与 ec101-mvp-db 结论对照", "", f"核算日：{CALC_DATE}。旧库结论来自 `mvp/ec101_mvp.db`（与 https://github.com/Zzh032811/ec101-mvp-db 的舟谱 RESULT 一致）。", "", "| 指标 | 旧库结论 | 本次结果 | 是否一致 |", "|---|---:|---:|---|"]
    mismatches = 0
    for name, expected in REFERENCE.items():
        actual = metrics[name]
        same = abs(float(actual) - float(expected)) < 0.001
        mismatches += int(not same)
        lines.append(f"| {name} | {expected:g} | {float(actual):g} | {'一致' if same else '不一致'} |")
    lines.extend(["", "## 转换报告", "", "```", conversion_report.strip(), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return mismatches


def main() -> int:
    output_dir = ROOT / "outputs" / "zhoupu-yibai-standard"
    request = ConversionRequest("舟谱", "羿柏", pilot_source_paths(ROOT / "舟谱-羿柏-试点"), [GIFT_ACTIVITY], [COUPON_CONFIG], output_dir)
    print("转换舟谱试点...")
    converted = convert_zhoupu_snapshot(request)
    print(converted.report_path.read_text(encoding="utf-8"))
    print("读取标准工作簿...")
    workbook = read_standard_workbook(converted.workbook_path)
    db_path = ROOT / "mvp" / "ec101_standard.db"
    if db_path.exists():
        db_path.unlink()
    create_database(db_path)
    print("导入并核算...")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        imported = import_snapshot(
            connection, workbook,
            ArchiveMetadata(str(converted.sources_zip_path), _sha256(converted.sources_zip_path), converted.sources_zip_path.stat().st_size),
            calc_date=CALC_DATE,
        )
        print(f"import_batch={imported.import_batch_id} calculation_run={imported.calculation_run_id} status={imported.status}")
        metrics = _metrics(connection)
        fk = connection.execute("PRAGMA foreign_key_check").fetchall()
    report_path = output_dir / "comparison.md"
    mismatches = _write_report(report_path, metrics, converted.report_path.read_text(encoding="utf-8"))
    print(report_path.read_text(encoding="utf-8"))
    print(f"foreign_key_check={fk or '通过'} mismatches={mismatches}")
    return 1 if mismatches or fk else 0


if __name__ == "__main__":
    raise SystemExit(main())
