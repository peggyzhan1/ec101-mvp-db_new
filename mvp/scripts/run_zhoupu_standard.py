# -*- coding: utf-8 -*-
"""把舟谱-羿柏试点转成标准工作簿，导入标准库并核算。

不删除已有标准库。同一经销商、平台和覆盖区间的上一份批次会标成非当前，其他平台保留。
"""
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
    "券实际发生": 720.0,
    "券已归因金额": 675.0,
    "券可释放": 555.0,
    "活动核销行": 0,
    "满赠实发": 111.0,
    "满赠可释放": 100.0,
    "双单号警告": 1,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metrics(connection: sqlite3.Connection, batch_id: int) -> dict[str, float]:
    def one(sql: str) -> float:
        value = connection.execute(sql, (batch_id,)).fetchone()[0]
        return 0 if value is None else value
    return {
        "客户主数据": one("SELECT COUNT(*) FROM customer WHERE import_batch_id=? AND customer_no NOT LIKE 'UNRESOLVED:%'"),
        "商品主数据": one("SELECT COUNT(*) FROM product WHERE import_batch_id=? AND product_no NOT LIKE 'UNMATCHED:%'"),
        "订单": one("SELECT COUNT(*) FROM order_header WHERE import_batch_id=?"),
        "XD-only订单": one("SELECT COUNT(*) FROM order_header WHERE import_batch_id=? AND order_source='XD履约(无SXD)'"),
        "订单行": one("SELECT COUNT(*) FROM order_line ol JOIN order_header oh ON oh.order_id=ol.order_id WHERE oh.import_batch_id=?"),
        "履约": one("SELECT COUNT(*) FROM fulfillment WHERE import_batch_id=?"),
        "券台账": one("SELECT COUNT(*) FROM coupon_redemption WHERE import_batch_id=?"),
        "已用券": one("SELECT COUNT(*) FROM coupon_redemption WHERE import_batch_id=? AND status='已使用'"),
        "返券归因订单": one("SELECT COUNT(*) FROM coupon_redemption WHERE import_batch_id=? AND status='已使用' AND order_id IS NOT NULL"),
        "券实际发生": one("SELECT COALESCE(coupon_benefit,0) FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1"),
        "券已归因金额": one("SELECT COALESCE(SUM(linked_amount),0) FROM coupon_fee_summary WHERE calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=?)"),
        "券可释放": one("SELECT COALESCE(SUM(releasable_amount),0) FROM coupon_fee_summary WHERE calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=?)"),
        "活动核销行": one("SELECT COUNT(*) FROM activity_execution e JOIN activity a ON a.activity_id=e.activity_id WHERE a.import_batch_id=?"),
        "满赠实发": one("SELECT COALESCE(SUM(gift_qty_actual),0) FROM activity_fee_summary WHERE calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=?)"),
        "满赠可释放": one("SELECT COALESCE(SUM(releasable_gift_qty),0) FROM activity_fee_summary WHERE calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=?)"),
        "双单号警告": one("SELECT COUNT(*) FROM calculation_quality_issue WHERE calculation_run_id=(SELECT MAX(calculation_run_id) FROM calculation_run WHERE import_batch_id=?) AND issue_type='返券双单号无法唯一归因'"),
    }


def _write_report(path: Path, metrics: dict[str, float], conversion_report: str) -> int:
    lines = ["# 舟谱-羿柏实际发生核算", "", f"核算日：{CALC_DATE}。导入标准工作簿后，只统计 CORE 里已经发生的赠品和已使用优惠券，再按「订单已完成且下单时间 ≤ 核算日减 2 天」计算可释放。", "", "| 指标 | 预期 | 本次结果 | 是否一致 |", "|---|---:|---:|---|"]
    mismatches = 0
    for name, expected in REFERENCE.items():
        actual = metrics[name]
        same = abs(float(actual) - float(expected)) < 0.001
        mismatches += int(not same)
        lines.append(f"| {name} | {expected:g} | {float(actual):g} | {'一致' if same else '不一致'} |")
    lines.extend([
        "",
        "双单号券记成一条警告：3 张、45 元已经计入实际发生，不能释放。",
        "",
        "## 待核对：满赠实发是否只认 XD",
        "",
        "当前实发 111，是活动窗口内商品名称为「(赠品)雪碧抱枕」的订单行合计。核算器没有按履约单再筛一次，这次也不改。",
        "",
        "- 82 个：SXD 有下游 XD，XD 文件里有抱枕行，履约状态已完成。",
        "- 18 个：没有上游 SXD 的 XD 履约单，抱枕写在 XD 上，状态已完成。",
        "- 11 个：抱枕只出现在 SXD 明细上，SXD 状态是已下发。单上写了下游 XD 单号，但这 11 张 XD 不在履约文件里。",
        "",
        "业务口径：SXD 显示已下发不算实发，只有 XD 履约单上出现赠品才算实发。按这个口径，实发是 82 + 18 = 100，上面 11 个不计入。核算器尚未按此调整。",
        "",
        "## 转换报告",
        "",
        "```",
        conversion_report.strip(),
        "```",
        "",
    ])
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
    if not db_path.exists():
        create_database(db_path)
    print("导入并核算，保留其他经销商...")
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        imported = import_snapshot(
            connection, workbook,
            ArchiveMetadata(str(converted.sources_zip_path), _sha256(converted.sources_zip_path), converted.sources_zip_path.stat().st_size),
            calc_date=CALC_DATE,
        )
        print(f"import_batch={imported.import_batch_id} calculation_run={imported.calculation_run_id} status={imported.status}")
        metrics = _metrics(connection, imported.import_batch_id)
        fk = connection.execute("PRAGMA foreign_key_check").fetchall()
    report_path = output_dir / "comparison.md"
    mismatches = _write_report(report_path, metrics, converted.report_path.read_text(encoding="utf-8"))
    print(report_path.read_text(encoding="utf-8"))
    print(f"foreign_key_check={fk or '通过'} mismatches={mismatches}")
    return 1 if mismatches or fk else 0


if __name__ == "__main__":
    raise SystemExit(main())
