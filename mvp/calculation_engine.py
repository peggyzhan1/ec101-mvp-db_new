"""Settle one imported batch into RESULT tables. Does not read Excel or know platforms."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from mvp.scripts.promotion_calculator import TemplateResult
from mvp.standard_promotion import consistency_of, recacl_activity_execution, recacl_coupon_redemption

RELEASED_REASON = "已完成且达到T-2"
RELEASE_LAG_DAYS = 2


def parse_calc_date(calc_date: str | None) -> str:
    """Return YYYY-MM-DD. Missing values become today; other formats raise ValueError."""
    if not calc_date:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(calc_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("核算日必须是 YYYY-MM-DD") from exc
    return calc_date


def release_cutoff(calc_date: str) -> str:
    """Orders placed before this instant (核算日 00:00 减两天) are old enough to be released."""
    day = datetime.strptime(parse_calc_date(calc_date), "%Y-%m-%d")
    return (day - timedelta(days=RELEASE_LAG_DAYS)).strftime("%Y-%m-%d %H:%M:%S")


def release_reason(order_status: str, order_time: str | None, cutoff: str) -> tuple[bool, str]:
    if order_status != "已完成":
        return False, f"订单状态={order_status or '空'}"
    if not order_time:
        return False, "下单时间缺失"
    if order_time >= cutoff:
        return False, f"未达T-2(下单 {order_time[:16]})"
    return True, RELEASED_REASON


def _decimal(value) -> float:
    return float(value or 0)


def calculate_batch(db: sqlite3.Connection, batch_id: int, calc_date: str | None = None) -> int:
    """Settle one import batch: 费用只来自核销；有规则时用 promotion_calculator 重算理论权益做核对。"""
    previous_factory = db.row_factory
    db.row_factory = sqlite3.Row
    try:
        return _calculate_batch(db, batch_id, calc_date)
    finally:
        db.row_factory = previous_factory


def _calculate_batch(db: sqlite3.Connection, batch_id: int, calc_date: str | None = None) -> int:
    db.row_factory = sqlite3.Row
    calc_date = parse_calc_date(calc_date)
    cutoff = release_cutoff(calc_date)
    activity_benefit = db.execute("SELECT COALESCE(SUM(discount_amount),0) FROM activity_execution WHERE activity_id IN (SELECT activity_id FROM activity WHERE import_batch_id=?)", (batch_id,)).fetchone()[0]
    coupon_benefit = db.execute("SELECT COALESCE(SUM(discount_amount),0) FROM coupon_redemption WHERE import_batch_id=?", (batch_id,)).fetchone()[0]
    calc_id = db.execute(
        "INSERT INTO calculation_run(import_batch_id,calc_date,release_cutoff,activity_benefit,coupon_benefit,total_benefit,status) VALUES(?,?,?,?,?,?,?)",
        (batch_id, calc_date, cutoff, activity_benefit, coupon_benefit, activity_benefit + coupon_benefit, "calculating"),
    ).lastrowid
    participating = db.execute(
        """
        SELECT oh.order_id, oh.order_no, oh.order_status, oh.order_time,
               COALESCE((SELECT SUM(ae.discount_amount) FROM activity_execution ae WHERE ae.order_id=oh.order_id), 0) AS activity_benefit,
               COALESCE((SELECT SUM(cr.discount_amount) FROM coupon_redemption cr WHERE cr.order_id=oh.order_id), 0) AS coupon_benefit
        FROM order_header oh
        WHERE oh.import_batch_id=? AND (
            EXISTS(SELECT 1 FROM activity_execution ae WHERE ae.order_id=oh.order_id)
            OR EXISTS(SELECT 1 FROM coupon_redemption cr WHERE cr.order_id=oh.order_id))
        ORDER BY oh.order_time, oh.order_no
        """,
        (batch_id,),
    ).fetchall()
    released_orders = 0
    released_activity = released_coupon = 0.0
    theoretical_activity_total = theoretical_coupon_total = 0.0
    consistent_orders = 0
    for order_id, order_no, order_status, order_time, act, coupon in participating:
        activity_result: TemplateResult | None = None
        coupon_result: TemplateResult | None = None
        formula_parts: list[str] = []
        gift_entitled = gift_actual = None
        executions = list(db.execute(
            "SELECT ae.*, a.activity_id, a.activity_type, a.start_time, a.end_time FROM activity_execution ae JOIN activity a ON a.activity_id=ae.activity_id WHERE ae.order_id=?",
            (order_id,),
        ))
        for execution in executions:
            activity = db.execute("SELECT * FROM activity WHERE activity_id=?", (execution["activity_id"],)).fetchone()
            result = recacl_activity_execution(db, activity, execution, order_time)
            if result is None:
                continue
            activity_result = result
            formula_parts.append(result.formula_ref)
            theoretical_activity_total += _decimal(result.theoretical_benefit)
            if result.gift_qty_entitled is not None:
                gift_entitled = _decimal(result.gift_qty_entitled)
            if result.gift_qty_actual is not None:
                gift_actual = _decimal(result.gift_qty_actual)
        redemptions = list(db.execute("SELECT * FROM coupon_redemption WHERE order_id=?", (order_id,)))
        for redemption in redemptions:
            result = recacl_coupon_redemption(db, batch_id, redemption, order_id, order_no, order_time)
            if result is None:
                continue
            coupon_result = result
            formula_parts.append(result.formula_ref)
            theoretical_coupon_total += _decimal(result.theoretical_benefit)
        has_rule = activity_result is not None or coupon_result is not None
        consistency = consistency_of(activity_result, coupon_result, has_rule)
        if consistency == "一致":
            consistent_orders += 1
        is_candidate, reason = release_reason(order_status, order_time, cutoff)
        db.execute(
            "INSERT INTO entitlement_check(calculation_run_id,order_id,activity_benefit,coupon_benefit,total_benefit,consistency,theoretical_activity_benefit,theoretical_coupon_benefit,gift_qty_entitled,gift_qty_actual,formula_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                calc_id, order_id, act, coupon, act + coupon, consistency,
                None if activity_result is None else _decimal(activity_result.theoretical_benefit),
                None if coupon_result is None else _decimal(coupon_result.theoretical_benefit),
                gift_entitled, gift_actual, ";".join(formula_parts) or None,
            ),
        )
        db.execute("INSERT INTO release_candidate(calculation_run_id,order_id,is_candidate,reason,activity_benefit,coupon_benefit) VALUES(?,?,?,?,?,?)",
                   (calc_id, order_id, int(is_candidate), reason, act, coupon))
        if is_candidate:
            released_orders += 1
            released_activity += act
            released_coupon += coupon
        else:
            db.execute("INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
                       (calc_id, order_no, "未达释放节点", "提示", reason))
        if consistency == "差异":
            db.execute("INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
                       (calc_id, order_no, "理论权益与实际执行不一致", "警告", ";".join(formula_parts) or "规则重算"))
    for activity_id, in db.execute("SELECT activity_id FROM activity WHERE import_batch_id=? ORDER BY activity_id", (batch_id,)).fetchall():
        totals = db.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(ae.discount_amount),0),
                   COALESCE(SUM(CASE WHEN rc.is_candidate=1 THEN 1 ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN rc.is_candidate=1 THEN ae.discount_amount ELSE 0 END),0)
            FROM activity_execution ae
            JOIN release_candidate rc ON rc.order_id=ae.order_id AND rc.calculation_run_id=?
            WHERE ae.activity_id=?
            """,
            (calc_id, activity_id),
        ).fetchone()
        orders, amount, released, released_amount = totals
        if orders == 0:
            continue
        db.execute(
            "INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,participating_orders,released_orders,released_amount,pending_orders,pending_amount) VALUES(?,?,?,?,?,?,?,?,?)",
            (calc_id, activity_id, round(amount, 2), 0, orders, released, round(released_amount, 2), orders - released, round(amount - released_amount, 2)),
        )
    db.execute(
        "UPDATE calculation_run SET released_activity_benefit=?, released_coupon_benefit=?, theoretical_activity_benefit=?, theoretical_coupon_benefit=?, consistent_orders=?, participating_orders=?, released_orders=?, status='calculated' WHERE calculation_run_id=?",
        (round(released_activity, 2), round(released_coupon, 2), round(theoretical_activity_total, 2), round(theoretical_coupon_total, 2), consistent_orders, len(participating), released_orders, calc_id),
    )
    db.execute("UPDATE import_batch SET status='calculated' WHERE import_batch_id=?", (batch_id,))
    return calc_id


def run_calculation(db: sqlite3.Connection, import_batch_id: int) -> dict[str, Any]:
    row = db.execute(
        "SELECT calculation_run_id,calc_date,release_cutoff,activity_benefit,coupon_benefit,total_benefit,released_activity_benefit,released_coupon_benefit,theoretical_activity_benefit,theoretical_coupon_benefit,consistent_orders,participating_orders,released_orders,status FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1",
        (import_batch_id,),
    ).fetchone()
    if row is None:
        raise ValueError("导入批次尚未产生核算结果")
    keys = (
        "calculation_run_id", "calc_date", "release_cutoff", "activity_benefit", "coupon_benefit", "total_benefit",
        "released_activity_benefit", "released_coupon_benefit", "theoretical_activity_benefit", "theoretical_coupon_benefit",
        "consistent_orders", "participating_orders", "released_orders", "status",
    )
    return dict(zip(keys, row))
