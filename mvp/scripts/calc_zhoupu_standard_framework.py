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
        f"这次算的是 `{WORKBOOK.relative_to(ROOT)}`，核算日 {CALC_DATE}。参加名单、应发权益和释放都由 `calculate_activity` 按标准表里的规则计算。",
        "",
        f"标准表里的活动核销明细有 {execution_rows} 行。订单明细里写了活动编号的有 {tagged_lines} 行。优惠券核销明细有 {coupon_rows} 行。",
        "",
    ]
    for prepared, summary in results:
        lines.append(f"## {prepared.name}")
        lines.append("")
        counts = connection.execute(
            """SELECT COUNT(*),
                      SUM(CASE WHEN consistency='一致' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN consistency='差异' THEN 1 ELSE 0 END)
               FROM result_entitlement
               WHERE order_activity_id IN (SELECT order_activity_id FROM order_activity WHERE activity_id=?)""",
            (prepared.activity_id,),
        ).fetchone()
        release = connection.execute(
            """SELECT SUM(CASE WHEN is_candidate=1 THEN 1 ELSE 0 END), SUM(CASE WHEN is_candidate=0 THEN 1 ELSE 0 END)
               FROM result_release_candidate
               WHERE order_id IN (SELECT order_id FROM order_activity WHERE activity_id=?)""",
            (prepared.activity_id,),
        ).fetchone()
        if summary.template == "gift":
            lines.append(f"参加 {counts[0]} 笔，应赠 {summary.gift_qty_entitled}，实赠 {summary.gift_qty_actual}，一致 {counts[1]}，差异 {counts[2]}。")
            lines.append(f"释放：已完成且到了核算日减 2 天的 {release[0]} 笔，未到释放节点的 {release[1]} 笔。可结算候选还要求权益一致，所以是 {summary.release_candidates} 笔。")
        else:
            lines.append(f"进入核算的券订单 {counts[0]} 笔，理论金额 {summary.theoretical_benefit}，实际金额 {summary.actual_benefit}，一致 {counts[1]}，差异 {counts[2]}。")
            lines.append(f"费用里的优惠总额是实际金额。其中订单已完成且到了核算日减 2 天的有 {release[0]} 笔，未到释放节点的 {release[1]} 笔。")
        for note in prepared.notes:
            lines.append(f"- {note}")
        lines.append("")
    report = OUTPUT / "comparison.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    connection.close()


if __name__ == "__main__":
    main()
