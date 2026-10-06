# -*- coding: utf-8 -*-
"""用 ec101-mvp-db 的 promotion_calculator 重算舟谱返券和满赠。

只读 mvp/ec101_mvp.db，结果写到副本，避免覆盖已核验批次。
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from promotion_calculator import calculate_activity

SOURCE = ROOT / "mvp" / "ec101_mvp.db"
OUTPUT = ROOT / "outputs" / "zhoupu-framework-recalc"
DB = OUTPUT / "ec101_mvp_recalc.db"
CALC_DATE = "2026-09-23"
ACTIVITIES = ("可口可乐产品288返15元券", "雪碧系列满100元送抱枕")


def _baseline(connection: sqlite3.Connection, activity_id: int, batch_id: int) -> dict:
    entitlement = connection.execute(
        """SELECT COUNT(*),
                  SUM(CASE WHEN consistency='一致' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN consistency='差异' THEN 1 ELSE 0 END),
                  COALESCE(SUM(theoretical_benefit),0),
                  COALESCE(SUM(platform_actual_benefit),0),
                  COALESCE(SUM(gift_qty_entitled),0),
                  COALESCE(SUM(gift_qty_actual),0)
           FROM result_entitlement
           WHERE calc_batch_id=? AND order_activity_id IN (SELECT order_activity_id FROM order_activity WHERE activity_id=?)""",
        (batch_id, activity_id),
    ).fetchone()
    fee = connection.execute(
        "SELECT actual_discount_total, settle_amount, settle_status FROM result_fee WHERE calc_batch_id=? AND activity_id=?",
        (batch_id, activity_id),
    ).fetchone()
    release = connection.execute(
        """SELECT SUM(CASE WHEN is_candidate=1 THEN 1 ELSE 0 END), SUM(CASE WHEN is_candidate=0 THEN 1 ELSE 0 END)
           FROM result_release_candidate
           WHERE calc_batch_id=? AND order_id IN (SELECT order_id FROM order_activity WHERE activity_id=?)""",
        (batch_id, activity_id),
    ).fetchone()
    return {"entitlement": entitlement, "fee": fee, "release": release}


def _explain(connection: sqlite3.Connection) -> list[str]:
    gift = connection.execute("SELECT start_time, end_time FROM activity WHERE activity_id=18").fetchone()
    outside = connection.execute(
        """SELECT COUNT(*) FROM order_activity oa JOIN order_header o ON o.order_id=oa.order_id
           WHERE oa.activity_id=18 AND (o.order_time < ? OR o.order_time > ?)""",
        (gift["start_time"], gift["end_time"]),
    ).fetchone()[0]
    scopes = [row[0] for row in connection.execute("SELECT scope_value FROM activity_scope WHERE activity_id=18 AND scope_category='商品'")]
    marks = ",".join("?" * len(scopes))
    name_hits = connection.execute(
        f"""SELECT COUNT(DISTINCT oa.order_id) FROM order_activity oa
            JOIN order_line ol ON ol.order_id=oa.order_id JOIN product p ON p.product_id=ol.product_id
            WHERE oa.activity_id=18 AND p.product_name IN ({marks})""",
        scopes,
    ).fetchone()[0]
    code_hits = connection.execute(
        f"""SELECT COUNT(DISTINCT oa.order_id) FROM order_activity oa
            JOIN order_line ol ON ol.order_id=oa.order_id JOIN product p ON p.product_id=ol.product_id
            WHERE oa.activity_id=18 AND (p.platform_product_no IN ({marks}) OR p.brand IN ({marks}))""",
        scopes + scopes,
    ).fetchone()[0]
    ledger = connection.execute(
        "SELECT COUNT(*), SUM(activity_id IS NULL), SUM(receive_time IS NULL), SUM(use_time IS NULL) FROM coupon_ledger WHERE activity_id IS NULL OR activity_id<>20"
    ).fetchone()
    rules = connection.execute("SELECT GROUP_CONCAT(activity_id) FROM coupon_issue_rule").fetchone()[0]
    return [
        "",
        "## 和旧结论为什么不同",
        "",
        "参与集合没有变：返券仍是 45 笔 `order_activity`，满赠仍是 142 笔。变的是理论权益和费用。",
        "",
        f"- 返券模板要同时连上 `coupon_ledger`、`coupon_issue_rule`、`coupon_use_rule`，并且券上要有 `activity_id`、领取时间和使用时间。舟谱这 {ledger[0]} 张券里 {ledger[1]} 张没有活动编号，领取时间为空 {ledger[2]} 张，使用时间为空 {ledger[3]} 张。发放规则只挂在活动 {rules}。45 笔因此理论 0、实际 0，公式引用是 `coupon_ledger eligibility`。`order_activity.platform_actual_benefit` 上的 675 元这套模板不读取。券实际合计为 0 时框架不写费用行。",
        f"- 满赠范围是 {len(scopes)} 个商品名称。框架只把范围值去对商品货号和品牌，对得上的订单是 {code_hits}。同一批订单按商品名称对范围，对得上的是 {name_hits}。范围失败后应赠数量为 0。实赠仍取 `gift_qty_actual`：42 笔实赠 0，判一致；100 笔实赠 1，判差异。",
        f"- 满赠活动窗口存在库里的是 {gift['start_time']} 至 {gift['end_time']}，有 {outside} 笔订单落在窗外。142 笔的活动商品金额都不少于 100，门槛不是应赠变成 0 的原因。",
        "- 框架按订单给赠品数量，没有「每客户一次」去重。旧结论的应赠 135 来自那次去重。",
        "- 释放行仍按「已完成且下单时间不晚于核算日减 2 天」写 `is_candidate`：满赠 142 笔都是候选，返券 37 笔候选、8 笔非候选。汇总里的可结算候选还要求权益一致，所以满赠汇总是 42，返券汇总是 37。",
        "- 100 条差异警告的文本写的是金额「理论=0.00;实际=0.00」。赠品数量差记在 `gift_qty_entitled` / `gift_qty_actual`，警告句子用的是金额字段。8 条提示是返券订单未完成。",
    ]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, DB)
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    old_batch = connection.execute("SELECT MAX(calc_batch_id) FROM result_calc_batch WHERE operator='舟谱RESULT'").fetchone()[0]
    # result_entitlement 对 order_activity_id 唯一，框架按同一计算批次替换原结果。
    new_batch = old_batch
    lines = [
        "# 舟谱按 promotion_calculator 通用框架重算",
        "",
        f"框架：`mvp/scripts/promotion_calculator.py` 的 `calculate_activity`。核算日 {CALC_DATE}。源库 `mvp/ec101_mvp.db` 未改动；副本批次 {new_batch} 上的权益、费用和释放由框架替换。",
        "",
        "参与订单沿用库里已有的 `order_activity`，框架不另行从订单行补订单。理论权益按活动规则、活动窗口和 `activity_scope` 计算，再与 `order_activity` 上的平台实际比较。释放看订单状态「已完成」且下单时间不晚于核算日减 2 天。",
        "",
    ]
    connection.execute("DELETE FROM result_quality_issue WHERE calc_batch_id=?", (new_batch,))
    activities = []
    for name in ACTIVITIES:
        activity_id = connection.execute("SELECT activity_id FROM activity WHERE activity_name=?", (name,)).fetchone()[0]
        activities.append((name, activity_id, _baseline(connection, activity_id, old_batch)))
    summaries = {}
    for name, activity_id, _before in activities:
        summaries[name] = calculate_activity(connection, activity_id, new_batch, CALC_DATE)
    for name, activity_id, before in activities:
        summary = summaries[name]
        after = _baseline(connection, activity_id, new_batch)
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- 模板：{summary.template}")
        lines.append(f"- 框架汇总：理论 {summary.theoretical_benefit}，实际 {summary.actual_benefit}，应赠 {summary.gift_qty_entitled}，实赠 {summary.gift_qty_actual}，可结算候选 {summary.release_candidates}，结算金额 {summary.settle_amount}")
        lines.append(f"- 原批次权益：订单 {before['entitlement'][0]}，一致 {before['entitlement'][1]}，差异 {before['entitlement'][2]}，理论金额 {before['entitlement'][3]}，实际金额 {before['entitlement'][4]}，应赠 {before['entitlement'][5]}，实赠 {before['entitlement'][6]}")
        lines.append(f"- 新批次权益：订单 {after['entitlement'][0]}，一致 {after['entitlement'][1]}，差异 {after['entitlement'][2]}，理论金额 {after['entitlement'][3]}，实际金额 {after['entitlement'][4]}，应赠 {after['entitlement'][5]}，实赠 {after['entitlement'][6]}")
        lines.append(f"- 原费用：{tuple(before['fee']) if before['fee'] else None}")
        lines.append(f"- 新费用：{tuple(after['fee']) if after['fee'] else None}")
        lines.append(f"- 原释放：候选 {before['release'][0]}，非候选 {before['release'][1]}")
        lines.append(f"- 新释放：候选 {after['release'][0]}，非候选 {after['release'][1]}")
        lines.append("")
    issues = connection.execute(
        "SELECT issue_type, level, reason, COUNT(*) FROM result_quality_issue WHERE calc_batch_id=? GROUP BY issue_type, level, reason ORDER BY COUNT(*) DESC",
        (new_batch,),
    ).fetchall()
    lines.append("## 新批次质量问题")
    lines.append("")
    for issue_type, level, reason, count in issues:
        lines.append(f"- {level} {issue_type}：{count}。{reason}")
    lines.extend(_explain(connection))
    lines.append("")
    report = OUTPUT / "comparison.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    connection.close()


if __name__ == "__main__":
    main()
