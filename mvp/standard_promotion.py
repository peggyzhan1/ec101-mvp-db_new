"""Apply promotion_calculator templates to standard-schema CORE facts.

Fees stay on redemption amounts. These helpers only produce theoretical
entitlement and consistency for orders that already participate.
"""

from __future__ import annotations

import sqlite3

from mvp.scripts.promotion_calculator import TemplateResult, _parse, calculate_coupon, calculate_discount, calculate_gift


def _in_window(start: str | None, end: str | None, order_time: str | None) -> bool:
    if not start or not end:
        return True
    value = _parse(order_time)
    begin, finish = _parse(start), _parse(end)
    return bool(value and begin and finish and begin <= value <= finish)


def _first_rule(db: sqlite3.Connection, activity_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM activity_rule WHERE activity_id=? ORDER BY activity_rule_id LIMIT 1",
        (activity_id,),
    ).fetchone()


def _gift_qty(db: sqlite3.Connection, activity_id: int, rule_no: str | None) -> float | None:
    row = db.execute(
        "SELECT gift_qty FROM activity_benefit WHERE activity_id=? AND benefit_type='赠品' AND (? IS NULL OR rule_no=?) ORDER BY activity_benefit_id LIMIT 1",
        (activity_id, rule_no, rule_no),
    ).fetchone()
    return None if row is None else row[0]


def _gift_product_no(db: sqlite3.Connection, activity_id: int) -> str | None:
    row = db.execute(
        "SELECT gift_product_no FROM activity_benefit WHERE activity_id=? AND benefit_type='赠品' AND gift_product_no IS NOT NULL AND gift_product_no!='' LIMIT 1",
        (activity_id,),
    ).fetchone()
    return None if row is None else row[0]


def _actual_gift_qty(db: sqlite3.Connection, order_id: int, gift_product_no: str | None) -> float | None:
    if not gift_product_no:
        return None
    row = db.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM order_line WHERE order_id=? AND product_no=?",
        (order_id, gift_product_no),
    ).fetchone()
    return row[0] if row else 0


def _activity_template(activity_type: str | None, db: sqlite3.Connection, activity_id: int) -> str:
    text = activity_type or ""
    if "赠" in text:
        return "gift"
    if db.execute("SELECT 1 FROM activity_benefit WHERE activity_id=? AND benefit_type='赠品' LIMIT 1", (activity_id,)).fetchone():
        return "gift"
    return "discount"


def recacl_activity_execution(db: sqlite3.Connection, activity: sqlite3.Row, execution: sqlite3.Row, order_time: str | None) -> TemplateResult | None:
    rule = _first_rule(db, activity["activity_id"])
    if rule is None:
        return None
    qualifies = _in_window(activity["start_time"], activity["end_time"], order_time)
    facts = {
        "activity_product_amount": execution["product_amount"] or 0,
        "platform_actual_benefit": execution["discount_amount"] or 0,
        "gift_qty_actual": _actual_gift_qty(db, execution["order_id"], _gift_product_no(db, activity["activity_id"])),
    }
    template = _activity_template(activity["activity_type"], db, activity["activity_id"])
    if template == "gift":
        return calculate_gift(rule, facts, qualifies, gift_qty=_gift_qty(db, activity["activity_id"], rule["rule_no"]))
    return calculate_discount(rule, facts, qualifies)


def _coupon_config_for_batch(db: sqlite3.Connection, batch_id: int) -> sqlite3.Row | None:
    rows = list(db.execute("SELECT * FROM coupon_config WHERE import_batch_id=?", (batch_id,)))
    if len(rows) == 1:
        return rows[0]
    return None


def recacl_coupon_redemption(db: sqlite3.Connection, batch_id: int, redemption: sqlite3.Row, order_id: int | None, order_no: str, order_time: str | None) -> TemplateResult | None:
    config = _coupon_config_for_batch(db, batch_id)
    if config is None:
        return None
    issue = db.execute("SELECT * FROM coupon_issue_rule WHERE coupon_config_id=?", (config["coupon_config_id"],)).fetchone()
    use = db.execute("SELECT * FROM coupon_use_rule WHERE coupon_config_id=?", (config["coupon_config_id"],)).fetchone()
    if issue is None or use is None:
        return None
    activity = db.execute(
        "SELECT * FROM activity WHERE import_batch_id=? AND activity_no=?",
        (batch_id, config["config_no"]),
    ).fetchone()
    if activity is None:
        return None
    rule = _first_rule(db, activity["activity_id"])
    if rule is None:
        return None
    product_amount = 0.0
    if order_id:
        row = db.execute("SELECT COALESCE(SUM(pre_discount_amount),0) FROM order_line WHERE order_id=?", (order_id,)).fetchone()
        product_amount = row[0] if row else 0
    ledger = {
        "coupon_status": redemption["status"],
        "receive_time": redemption["receive_time"],
        "use_time": redemption["used_at"],
        "discount_amount": redemption["discount_amount"] or 0,
        "issue_mode": issue["issue_mode"],
        "issue_start_at": issue["issue_start_at"],
        "issue_end_at": issue["issue_end_at"],
        "auto_issue_at": issue["auto_issue_at"],
        "use_start_at": use["use_start_at"],
        "use_end_at": use["use_end_at"],
        "validity_mode": use["validity_mode"],
        "valid_days_after_receive": use["valid_days_after_receive"],
    }
    qualifies = _in_window(activity["start_time"], activity["end_time"], order_time)
    facts = {"activity_product_amount": product_amount, "platform_actual_benefit": redemption["discount_amount"] or 0}
    return calculate_coupon(activity["activity_id"], rule, facts, qualifies, order_no, ledger=ledger)


def _qty_matches(result: TemplateResult) -> bool:
    if result.gift_qty_entitled is None:
        return result.theoretical_benefit == result.actual_benefit
    return result.gift_qty_actual is not None and result.gift_qty_entitled == result.gift_qty_actual


def consistency_of(activity_result: TemplateResult | None, coupon_result: TemplateResult | None, has_rule: bool) -> str:
    if not has_rule:
        return "按核销明细"
    results = [item for item in (activity_result, coupon_result) if item is not None]
    if not results:
        return "按核销明细"
    return "一致" if all(_qty_matches(result) for result in results) else "差异"
