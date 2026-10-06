"""Result calculation for one imported standard snapshot.

满减沿用活动核销金额。满赠按活动规则重算应赠数量，并和订单里的赠品行比较。
优惠券只计已挂到唯一订单的已使用券。已完成且履约完成时间不晚于核算日减 2 天的订单进入释放候选。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta


def calculate_results(db: sqlite3.Connection, import_batch_id: int, calc_date: str | None = None) -> int:
    calc_day = calc_date or datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.strptime(calc_day, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    gift_rows = _calculate_gifts(db, import_batch_id)
    _insert_gift_executions(db, gift_rows)
    activity_benefit = db.execute(
        "SELECT COALESCE(SUM(discount_amount),0) FROM activity_execution WHERE activity_id IN (SELECT activity_id FROM activity WHERE import_batch_id=?)",
        (import_batch_id,),
    ).fetchone()[0]
    coupon_benefit = db.execute(
        "SELECT COALESCE(SUM(discount_amount),0) FROM coupon_redemption WHERE import_batch_id=? AND order_id IS NOT NULL AND status='已使用'",
        (import_batch_id,),
    ).fetchone()[0]
    calc_id = db.execute(
        "INSERT INTO calculation_run(import_batch_id,calc_date,activity_benefit,coupon_benefit,total_benefit,status) VALUES(?,?,?,?,?,?)",
        (import_batch_id, calc_day, activity_benefit, coupon_benefit, activity_benefit + coupon_benefit, "calculated"),
    ).lastrowid
    mismatches = _money_mismatches(db, import_batch_id)
    participants = _participants(db, import_batch_id, gift_rows)
    for order_id, activity_amount, coupon_amount in participants:
        gift = gift_rows.get(order_id)
        entitled = gift["entitled"] if gift else None
        actual = gift["actual"] if gift else None
        consistent = "一致"
        if gift and abs(float(entitled) - float(actual)) > 0.001:
            consistent = "差异"
        if order_id in mismatches:
            consistent = "差异"
        db.execute(
            "INSERT INTO entitlement_check(calculation_run_id,order_id,activity_benefit,coupon_benefit,total_benefit,gift_qty_entitled,gift_qty_actual,consistency) VALUES(?,?,?,?,?,?,?,?)",
            (calc_id, order_id, activity_amount, coupon_amount, activity_amount + coupon_amount, entitled, actual, consistent),
        )
    _insert_release(db, calc_id, import_batch_id, [row[0] for row in participants], cutoff)
    _insert_fee_summaries(db, calc_id, import_batch_id, gift_rows)
    _insert_quality_issues(db, calc_id, import_batch_id, gift_rows, cutoff)
    return calc_id


def _calculate_gifts(db: sqlite3.Connection, import_batch_id: int) -> dict[int, dict]:
    activities = db.execute(
        """SELECT a.activity_id, a.start_time, a.end_time, b.gift_product_name, b.gift_qty
           FROM activity a JOIN activity_benefit b ON b.activity_id=a.activity_id
           WHERE a.import_batch_id=? AND b.benefit_type='赠品'""",
        (import_batch_id,),
    ).fetchall()
    results: dict[int, dict] = {}
    for activity_id, start_time, end_time, gift_name, gift_qty in activities:
        threshold = db.execute("SELECT threshold_value FROM activity_rule WHERE activity_id=? ORDER BY activity_rule_id LIMIT 1", (activity_id,)).fetchone()
        threshold_value = float(threshold[0] or 0) if threshold else 0.0
        prefixes = [row[0] for row in db.execute("SELECT scope_value FROM activity_scope WHERE activity_id=? AND scope_dimension='商品名称前缀'", (activity_id,))]
        limit_row = db.execute("SELECT scope_value FROM activity_scope WHERE activity_id=? AND scope_category='限购' AND scope_dimension='每客户次数'", (activity_id,)).fetchone()
        per_customer = int(float(limit_row[0])) if limit_row and limit_row[0] not in (None, "") else None
        each_gift = float(gift_qty or 1)
        orders = db.execute(
            """SELECT h.order_id, h.customer_no FROM order_header h
               WHERE h.import_batch_id=? AND h.order_time>=? AND h.order_time<=? AND h.order_status='已完成'
               AND EXISTS (SELECT 1 FROM fulfillment f WHERE f.import_batch_id=h.import_batch_id AND f.order_no=h.order_no AND f.fulfillment_status='已完成')
               ORDER BY h.customer_no, h.order_time, h.order_id""",
            (import_batch_id, start_time, end_time),
        ).fetchall()
        granted: set[str] = set()
        for order_id, customer_no in orders:
            scope_amount, actual_gift = _order_gift_amounts(db, import_batch_id, order_id, prefixes, gift_name or "")
            if scope_amount < threshold_value and actual_gift <= 0:
                continue
            if scope_amount >= threshold_value and (per_customer is None or customer_no not in granted):
                entitled = each_gift
                if per_customer is not None:
                    granted.add(customer_no)
            else:
                entitled = 0.0
            results[order_id] = {"activity_id": activity_id, "entitled": entitled, "actual": actual_gift, "scope_amount": scope_amount}
    return results


def _order_gift_amounts(db: sqlite3.Connection, import_batch_id: int, order_id: int, prefixes: list[str], gift_name: str) -> tuple[float, float]:
    scope_amount = 0.0
    actual_gift = 0.0
    rows = db.execute(
        """SELECT p.product_no, p.product_name, ol.pre_discount_amount, ol.quantity
           FROM order_line ol JOIN product p ON p.import_batch_id=? AND p.product_no=ol.product_no
           WHERE ol.order_id=?""",
        (import_batch_id, order_id),
    ).fetchall()
    for product_no, product_name, amount, quantity in rows:
        if str(product_no).startswith("UNMATCHED:"):
            continue
        name = product_name or ""
        if gift_name and name == gift_name:
            actual_gift += float(quantity or 0)
        elif any(name.startswith(prefix) for prefix in prefixes):
            scope_amount += float(amount or 0)
    return round(scope_amount, 2), round(actual_gift, 2)


def _insert_gift_executions(db: sqlite3.Connection, gift_rows: dict[int, dict]) -> None:
    for order_id, gift in gift_rows.items():
        order = db.execute("SELECT customer_no, customer_name FROM order_header WHERE order_id=?", (order_id,)).fetchone()
        db.execute(
            "INSERT OR IGNORE INTO activity_execution(activity_id,order_id,activity_name,customer_no,customer_name,salesperson,product_amount,discount_amount) VALUES(?,?,?,?,?,?,?,?)",
            (gift["activity_id"], order_id, "", order[0], order[1], "", round(gift["scope_amount"], 2), 0),
        )


def _money_mismatches(db: sqlite3.Connection, import_batch_id: int) -> set[int]:
    mismatched: set[int] = set()
    rows = db.execute(
        """SELECT e.order_id, e.product_amount, e.discount_amount, r.threshold_value, r.reduce_amount
           FROM activity_execution e JOIN activity a ON a.activity_id=e.activity_id
           JOIN activity_rule r ON r.activity_id=a.activity_id
           WHERE a.import_batch_id=? AND COALESCE(r.reduce_amount,0) > 0""",
        (import_batch_id,),
    ).fetchall()
    for order_id, product_amount, discount_amount, threshold_value, reduce_amount in rows:
        theoretical = float(reduce_amount or 0) if float(product_amount or 0) >= float(threshold_value or 0) else 0.0
        if abs(theoretical - float(discount_amount or 0)) > 0.01:
            mismatched.add(order_id)
    return mismatched


def _participants(db: sqlite3.Connection, import_batch_id: int, gift_rows: dict[int, dict]) -> list[tuple[int, float, float]]:
    order_ids = set(gift_rows)
    order_ids.update(row[0] for row in db.execute(
        "SELECT e.order_id FROM activity_execution e JOIN activity a ON a.activity_id=e.activity_id WHERE a.import_batch_id=?",
        (import_batch_id,),
    ))
    order_ids.update(row[0] for row in db.execute(
        "SELECT order_id FROM coupon_redemption WHERE import_batch_id=? AND order_id IS NOT NULL AND status='已使用'",
        (import_batch_id,),
    ))
    participants = []
    for order_id in sorted(order_ids):
        activity_amount = db.execute("SELECT COALESCE(SUM(e.discount_amount),0) FROM activity_execution e JOIN activity a ON a.activity_id=e.activity_id WHERE e.order_id=? AND a.import_batch_id=?", (order_id, import_batch_id)).fetchone()[0]
        coupon_amount = db.execute("SELECT COALESCE(SUM(discount_amount),0) FROM coupon_redemption WHERE import_batch_id=? AND order_id=? AND status='已使用'", (import_batch_id, order_id)).fetchone()[0]
        participants.append((order_id, float(activity_amount or 0), float(coupon_amount or 0)))
    return participants


def _insert_release(db: sqlite3.Connection, calc_id: int, import_batch_id: int, order_ids: list[int], cutoff: str) -> None:
    for order_id in order_ids:
        status, completed_at = db.execute(
            """SELECT h.order_status, f.completed_at FROM order_header h
               LEFT JOIN fulfillment f ON f.import_batch_id=h.import_batch_id AND f.order_no=h.order_no
               WHERE h.order_id=?""",
            (order_id,),
        ).fetchone()
        is_candidate = 1 if status == "已完成" and completed_at and completed_at <= cutoff else 0
        reason = "已完成且≤T-2" if is_candidate else "未完成或>T-2"
        db.execute(
            "INSERT INTO release_candidate(calculation_run_id,order_id,is_candidate,reason) VALUES(?,?,?,?)",
            (calc_id, order_id, is_candidate, reason),
        )


def _insert_fee_summaries(db: sqlite3.Connection, calc_id: int, import_batch_id: int, gift_rows: dict[int, dict]) -> None:
    activities = db.execute("SELECT activity_id, activity_type, promo_method FROM activity WHERE import_batch_id=?", (import_batch_id,)).fetchall()
    for activity_id, activity_type, promo_method in activities:
        is_gift = "赠" in (activity_type or "") or "赠" in (promo_method or "")
        discount_total = db.execute("SELECT COALESCE(SUM(discount_amount),0) FROM activity_execution WHERE activity_id=?", (activity_id,)).fetchone()[0]
        entitled = sum(row["entitled"] for row in gift_rows.values() if row["activity_id"] == activity_id)
        actual = sum(row["actual"] for row in gift_rows.values() if row["activity_id"] == activity_id)
        db.execute(
            "INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,gift_qty_entitled,gift_qty_actual,settle_status) VALUES(?,?,?,?,?,?,?)",
            (calc_id, activity_id, 0 if is_gift else discount_total, 0, entitled if is_gift else None, actual if is_gift else None, "按赠品数量统计(不结算单价)" if is_gift else "金额优惠"),
        )


def _insert_quality_issues(db: sqlite3.Connection, calc_id: int, import_batch_id: int, gift_rows: dict[int, dict], cutoff: str) -> None:
    unlinked = db.execute(
        "SELECT coupon_no, use_period, discount_amount FROM coupon_redemption WHERE import_batch_id=? AND status='已使用' AND order_id IS NULL",
        (import_batch_id,),
    ).fetchall()
    dual = [row for row in unlinked if str(row[1] or "").startswith("关联单据:") and "," in str(row[1])]
    if dual:
        amount = round(sum(float(row[2] or 0) for row in dual), 2)
        raw_numbers = [str(row[1]).removeprefix("关联单据:") for row in dual]
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "返券双单号无法唯一归因", "警告", f"{len(dual)}张已用券关联单据含多个订单号，未计入返券费用，涉及金额{amount}元；原始单号={raw_numbers}"),
        )
    other_unlinked = [row for row in unlinked if row not in dual]
    if other_unlinked:
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "返券单号未命中订单", "警告", f"{len(other_unlinked)}张已用券没有唯一订单，未计入返券费用"),
        )
    unmatched_customers = db.execute(
        """SELECT COUNT(*) FROM coupon_redemption c
           WHERE c.import_batch_id=? AND c.customer_no<>'' AND NOT EXISTS (
             SELECT 1 FROM customer k WHERE k.import_batch_id=c.import_batch_id AND k.customer_no=c.customer_no)""",
        (import_batch_id,),
    ).fetchone()[0]
    if unmatched_customers:
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "券领取客户未匹配", "警告", f"{unmatched_customers}张券的领取客户未命中客户主数据"),
        )
    differences = sum(1 for row in gift_rows.values() if row["entitled"] != row["actual"])
    if differences:
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "满赠应赠与实赠不一致", "警告", f"{differences}笔满赠订单应赠数量与实赠数量不一致，待业务核对"),
        )
    db.execute(
        "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
        (calc_id, None, "T-2释放口径", "提示", f"释放候选要求订单已完成，且履约完成时间≤{cutoff}"),
    )
