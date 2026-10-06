"""Settle one imported batch into RESULT tables. Does not read Excel or know platforms."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

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


def calculate_batch(db: sqlite3.Connection, batch_id: int, calc_date: str | None = None) -> int:
    """Settle one import batch: 费用只来自活动核销与券核销；订单事实只决定能否释放（已完成 + T-2）。"""
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
    for order_id, order_no, order_status, order_time, act, coupon in participating:
        is_candidate, reason = release_reason(order_status, order_time, cutoff)
        db.execute("INSERT INTO entitlement_check(calculation_run_id,order_id,activity_benefit,coupon_benefit,total_benefit,consistency) VALUES(?,?,?,?,?,?)",
                   (calc_id, order_id, act, coupon, act + coupon, "按核销明细"))
        db.execute("INSERT INTO release_candidate(calculation_run_id,order_id,is_candidate,reason,activity_benefit,coupon_benefit) VALUES(?,?,?,?,?,?)",
                   (calc_id, order_id, int(is_candidate), reason, act, coupon))
        if is_candidate:
            released_orders += 1
            released_activity += act
            released_coupon += coupon
        else:
            db.execute("INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
                       (calc_id, order_no, "未达释放节点", "提示", reason))
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
        db.execute(
            "INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,participating_orders,released_orders,released_amount,pending_orders,pending_amount) VALUES(?,?,?,?,?,?,?,?,?)",
            (calc_id, activity_id, round(amount, 2), 0, orders, released, round(released_amount, 2), orders - released, round(amount - released_amount, 2)),
        )
    db.execute(
        "UPDATE calculation_run SET released_activity_benefit=?, released_coupon_benefit=?, participating_orders=?, released_orders=?, status='calculated' WHERE calculation_run_id=?",
        (round(released_activity, 2), round(released_coupon, 2), len(participating), released_orders, calc_id),
    )
    db.execute("UPDATE import_batch SET status='calculated' WHERE import_batch_id=?", (batch_id,))
    return calc_id


def run_calculation(db: sqlite3.Connection, import_batch_id: int) -> dict[str, Any]:
    row = db.execute("SELECT calculation_run_id,calc_date,release_cutoff,activity_benefit,coupon_benefit,total_benefit,released_activity_benefit,released_coupon_benefit,participating_orders,released_orders,status FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1", (import_batch_id,)).fetchone()
    if row is None:
        raise ValueError("导入批次尚未产生核算结果")
    keys = ("calculation_run_id", "calc_date", "release_cutoff", "activity_benefit", "coupon_benefit", "total_benefit", "released_activity_benefit", "released_coupon_benefit", "participating_orders", "released_orders", "status")
    return dict(zip(keys, row))
