# -*- coding: utf-8 -*-
"""用 promotion_calculator 核算舟谱 standard.xlsx，不改框架规则。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mvp.standard_framework import calculate_standard_tables, open_calculator_db
from mvp.standard_workbook import read_standard_workbook

CALC_DATE = "2026-09-23"
WORKBOOK = ROOT / "outputs" / "zhoupu-yibai-standard" / "standard.xlsx"
OUTPUT = ROOT / "outputs" / "zhoupu-standard-framework"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    workbook = read_standard_workbook(WORKBOOK)
    tables = workbook.tables
    database = OUTPUT / "framework.db"
    database.unlink(missing_ok=True)
    connection = open_calculator_db(database)
    results = calculate_standard_tables(connection, tables, workbook.manifest["经销商名称"], workbook.manifest["平台名称"], CALC_DATE)
    execution_rows = len(tables.get("标准活动核销明细", []))
    coupon_rows = len(tables.get("标准优惠券核销明细", []))
    tagged_lines = sum(1 for row in tables.get("标准订单明细", []) if str(row.get("活动编号", "")).strip())
    lines = [
        "# 用通用核算框架算 standard.xlsx",
        "",
        f"这次算的是 `{WORKBOOK.relative_to(ROOT)}`，核算日 {CALC_DATE}。用的就是原来的 `calculate_activity`，判断规则没有改。",
        "",
        f"标准表里的活动核销明细有 {execution_rows} 行。订单明细里写了活动编号的有 {tagged_lines} 行。优惠券核销明细有 {coupon_rows} 行。",
        "",
    ]
    for prepared, summary in results:
        lines.append(f"## {prepared.name}")
        lines.append("")
        if summary.template == "gift":
            lines.append(f"参加名单 {prepared.order_count} 笔，应赠 {summary.gift_qty_entitled}，实赠 {summary.gift_qty_actual}。")
        else:
            lines.append(f"送进框架的券订单 {prepared.order_count} 笔，理论金额 {summary.theoretical_benefit}，实际金额 {summary.actual_benefit}，结算金额 {summary.settle_amount}。其中 {summary.release_candidates} 笔只是订单已经完成、并且下单时间到了核算日减 2 天，不代表算出了优惠金额。")
        for note in prepared.notes:
            lines.append(f"- {note}")
        lines.append("")
    report = OUTPUT / "comparison.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    connection.close()


if __name__ == "__main__":
    main()
