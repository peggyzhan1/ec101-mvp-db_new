"""Actual-only result calculation from CORE facts.

The calculator reads orders, activity executions, gift lines, and coupon
redemptions already stored for one import batch. It does not open the
standard workbook, and it does not recheck thresholds, scopes, or
per-customer limits.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta


def calculate_actual_results(db: sqlite3.Connection, import_batch_id: int, calc_date: str | None = None) -> int:
    calc_day = calc_date or datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.strptime(calc_day, "%Y-%m-%d") - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    orders = _orders(db, import_batch_id)
    activities = _activities(db, import_batch_id)
    benefits = _benefits(db, import_batch_id)
    executions = _executions(db, import_batch_id)
    occurrences: list[dict] = []
    issues: list[tuple[str, str, str]] = []
    for activity in activities:
        activity_id = activity["activity_id"]
        gifts = benefits.get(activity_id, [])
        is_gift = bool(gifts) or _text_is_gift(activity["activity_type"], activity["promo_method"])
        execution_rows = executions.get(activity_id, [])
        if execution_rows and is_gift:
            quantities = _gift_quantities(db, import_batch_id, gifts)
            missing = 0
            for order_id, _discount in execution_rows:
                actual = quantities.get(order_id, 0.0)
                if actual <= 0:
                    missing += 1
                occurrences.append(_occurrence(activity_id, order_id, 0.0, actual, True))
            if missing and gifts:
                issues.append(("核销订单没有赠品行", "警告", f"{missing}笔活动核销订单没有对应赠品行"))
            elif not gifts:
                issues.append(("赠品权益缺少赠品", "警告", f"活动 {activity['activity_no']} 标记为赠品，但没有赠品名称或编号"))
        elif execution_rows:
            for order_id, discount in execution_rows:
                occurrences.append(_occurrence(activity_id, order_id, discount, None, False))
        elif is_gift and gifts:
            quantities = _gift_quantities(db, import_batch_id, gifts, activity["start_time"], activity["end_time"])
            for order_id, actual in quantities.items():
                occurrences.append(_occurrence(activity_id, order_id, 0.0, actual, True))
        elif is_gift:
            issues.append(("赠品权益缺少赠品", "警告", f"活动 {activity['activity_no']} 标记为赠品，但没有赠品名称或编号"))
    coupons = _used_coupons(db, import_batch_id)
    configs = _coupon_configs(db, import_batch_id)
    buckets = _assign_coupons(coupons, configs)
    activity_benefit = round(sum(row["discount"] for row in occurrences if not row["is_gift"]), 2)
    coupon_benefit = round(sum(row["discount_amount"] for row in coupons), 2)
    calc_id = db.execute(
        "INSERT INTO calculation_run(import_batch_id,calc_date,activity_benefit,coupon_benefit,total_benefit,status) VALUES(?,?,?,?,?,?)",
        (import_batch_id, calc_day, activity_benefit, coupon_benefit, round(activity_benefit + coupon_benefit, 2), "calculated"),
    ).lastrowid
    _insert_entitlements(db, calc_id, occurrences)
    participant_ids = {row["order_id"] for row in occurrences}
    participant_ids.update(row["order_id"] for row in coupons if row["order_id"] is not None)
    _insert_release(db, calc_id, sorted(participant_ids), orders, cutoff)
    _insert_activity_fees(db, calc_id, activities, occurrences, orders, cutoff)
    _insert_coupon_fees(db, calc_id, configs, buckets, orders, cutoff)
    _insert_issues(db, calc_id, import_batch_id, coupons, issues, cutoff)
    return calc_id


def _occurrence(activity_id: int, order_id: int, discount: float, gift_qty: float | None, is_gift: bool) -> dict:
    return {"activity_id": activity_id, "order_id": order_id, "discount": round(discount, 2), "gift_qty": None if gift_qty is None else round(gift_qty, 2), "is_gift": is_gift}


def _orders(db: sqlite3.Connection, import_batch_id: int) -> dict[int, dict]:
    rows = db.execute(
        "SELECT order_id, order_no, order_status, order_time FROM order_header WHERE import_batch_id=?",
        (import_batch_id,),
    ).fetchall()
    return {row[0]: {"order_no": row[1], "status": row[2], "order_time": row[3]} for row in rows}


def _activities(db: sqlite3.Connection, import_batch_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT activity_id, activity_no, activity_name, activity_type, promo_method, start_time, end_time FROM activity WHERE import_batch_id=? ORDER BY activity_id",
        (import_batch_id,),
    ).fetchall()
    return [
        {"activity_id": row[0], "activity_no": row[1], "activity_name": row[2], "activity_type": row[3], "promo_method": row[4], "start_time": row[5], "end_time": row[6]}
        for row in rows
    ]


def _benefits(db: sqlite3.Connection, import_batch_id: int) -> dict[int, list[tuple[str, str]]]:
    rows = db.execute(
        """SELECT b.activity_id, b.gift_product_no, b.gift_product_name
           FROM activity_benefit b JOIN activity a ON a.activity_id=b.activity_id
           WHERE a.import_batch_id=? AND b.benefit_type='赠品'""",
        (import_batch_id,),
    ).fetchall()
    grouped: dict[int, list[tuple[str, str]]] = {}
    for activity_id, gift_no, gift_name in rows:
        number = (gift_no or "").strip()
        name = (gift_name or "").strip()
        if number or name:
            grouped.setdefault(activity_id, []).append((number, name))
    return grouped


def _executions(db: sqlite3.Connection, import_batch_id: int) -> dict[int, list[tuple[int, float]]]:
    rows = db.execute(
        """SELECT e.activity_id, e.order_id, COALESCE(e.discount_amount, 0)
           FROM activity_execution e JOIN activity a ON a.activity_id=e.activity_id
           WHERE a.import_batch_id=?""",
        (import_batch_id,),
    ).fetchall()
    grouped: dict[int, list[tuple[int, float]]] = {}
    for activity_id, order_id, discount in rows:
        grouped.setdefault(activity_id, []).append((order_id, float(discount or 0)))
    return grouped


def _gift_quantities(db: sqlite3.Connection, import_batch_id: int, gifts: list[tuple[str, str]], start_time: str | None = None, end_time: str | None = None) -> dict[int, float]:
    if not gifts:
        return {}
    match_sql = []
    params: list[object] = [import_batch_id]
    for gift_no, gift_name in gifts:
        if gift_name:
            match_sql.append("(ol.product_name=? OR p.product_name=?)")
            params.extend([gift_name, gift_name])
        if gift_no:
            match_sql.append("ol.product_no=?")
            params.append(gift_no)
    if not match_sql:
        return {}
    window_sql = ""
    if start_time is not None or end_time is not None:
        window_sql = " AND CASE WHEN length(h.order_time)=10 THEN h.order_time || ' 00:00:00' ELSE h.order_time END BETWEEN ? AND ?"
        params.extend([_stamp(start_time, "start"), _stamp(end_time, "end")])
    rows = db.execute(
        f"""SELECT h.order_id, COALESCE(SUM(ol.quantity), 0)
            FROM order_line ol
            JOIN order_header h ON h.order_id=ol.order_id
            LEFT JOIN product p ON p.import_batch_id=h.import_batch_id AND p.product_no=ol.product_no
            WHERE h.import_batch_id=? AND ({' OR '.join(match_sql)}){window_sql}
            GROUP BY h.order_id""",
        params,
    ).fetchall()
    return {row[0]: round(float(row[1] or 0), 2) for row in rows}


def _used_coupons(db: sqlite3.Connection, import_batch_id: int) -> list[dict]:
    rows = db.execute(
        """SELECT coupon_redemption_id, order_id, coupon_no, customer_no, use_period, COALESCE(discount_amount, 0)
           FROM coupon_redemption WHERE import_batch_id=? AND status='已使用'""",
        (import_batch_id,),
    ).fetchall()
    return [
        {"coupon_redemption_id": row[0], "order_id": row[1], "coupon_no": row[2] or "", "customer_no": row[3] or "", "use_period": row[4] or "", "discount_amount": round(float(row[5] or 0), 2)}
        for row in rows
    ]


def _coupon_configs(db: sqlite3.Connection, import_batch_id: int) -> list[tuple[int, str]]:
    return db.execute(
        "SELECT coupon_config_id, coupon_name FROM coupon_config WHERE import_batch_id=? ORDER BY coupon_config_id",
        (import_batch_id,),
    ).fetchall()


def _assign_coupons(coupons: list[dict], configs: list[tuple[int, str]]) -> dict[int | None, list[dict]]:
    buckets: dict[int | None, list[dict]] = {config_id: [] for config_id, _name in configs}
    if len(configs) == 1:
        buckets[configs[0][0]] = list(coupons)
        return buckets
    if not configs:
        buckets[None] = list(coupons)
        return buckets
    for coupon in coupons:
        matched = [config_id for config_id, name in configs if name and name in coupon["coupon_no"]]
        key = matched[0] if len(matched) == 1 else None
        buckets.setdefault(key, []).append(coupon)
    return buckets


def _insert_entitlements(db: sqlite3.Connection, calc_id: int, occurrences: list[dict]) -> None:
    for row in occurrences:
        db.execute(
            """INSERT INTO entitlement_check(calculation_run_id,order_id,activity_id,activity_benefit,coupon_benefit,total_benefit,gift_qty_entitled,gift_qty_actual,consistency)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (calc_id, row["order_id"], row["activity_id"], 0 if row["is_gift"] else row["discount"], 0, 0 if row["is_gift"] else row["discount"], None, row["gift_qty"], "已发生"),
        )


def _insert_release(db: sqlite3.Connection, calc_id: int, order_ids: list[int], orders: dict[int, dict], cutoff: str) -> None:
    for order_id in order_ids:
        order = orders.get(order_id)
        if order is None:
            continue
        is_candidate = 1 if _can_release(order, cutoff) else 0
        reason = "已完成且下单时间≤核算日减2天" if is_candidate else "订单未完成或下单时间晚于核算日减2天"
        db.execute(
            "INSERT INTO release_candidate(calculation_run_id,order_id,is_candidate,reason) VALUES(?,?,?,?)",
            (calc_id, order_id, is_candidate, reason),
        )


def _insert_activity_fees(db: sqlite3.Connection, calc_id: int, activities: list[dict], occurrences: list[dict], orders: dict[int, dict], cutoff: str) -> None:
    for activity in activities:
        rows = [row for row in occurrences if row["activity_id"] == activity["activity_id"]]
        is_gift = bool(rows) and rows[0]["is_gift"] or (not rows and _text_is_gift(activity["activity_type"], activity["promo_method"]))
        releasable = [row for row in rows if _can_release(orders.get(row["order_id"]), cutoff)]
        if is_gift or (rows and rows[0]["is_gift"]):
            actual_qty = round(sum(row["gift_qty"] or 0 for row in rows), 2)
            releasable_qty = round(sum(row["gift_qty"] or 0 for row in releasable), 2)
            db.execute(
                """INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,gift_qty_entitled,gift_qty_actual,releasable_discount_total,releasable_gift_qty,release_order_count,settle_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (calc_id, activity["activity_id"], 0, 0, None, actual_qty, 0, releasable_qty, len(releasable), "按赠品数量统计(不结算单价)"),
            )
        else:
            actual_amount = round(sum(row["discount"] for row in rows), 2)
            releasable_amount = round(sum(row["discount"] for row in releasable), 2)
            db.execute(
                """INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,gift_qty_entitled,gift_qty_actual,releasable_discount_total,releasable_gift_qty,release_order_count,settle_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (calc_id, activity["activity_id"], actual_amount, 0, None, None, releasable_amount, None, len(releasable), "金额优惠"),
            )


def _insert_coupon_fees(db: sqlite3.Connection, calc_id: int, configs: list[tuple[int, str]], buckets: dict[int | None, list[dict]], orders: dict[int, dict], cutoff: str) -> None:
    keys = [config_id for config_id, _name in configs]
    if None in buckets and buckets[None]:
        keys.append(None)
    for key in keys:
        rows = buckets.get(key, [])
        linked = [row for row in rows if row["order_id"] is not None]
        unlinked = [row for row in rows if row["order_id"] is None]
        releasable = [row for row in linked if _can_release(orders.get(row["order_id"]), cutoff)]
        db.execute(
            """INSERT INTO coupon_fee_summary(calculation_run_id,coupon_config_id,used_count,used_amount,linked_amount,releasable_count,releasable_amount,unlinked_count,unlinked_amount,settle_status)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                calc_id, key, len(rows), round(sum(row["discount_amount"] for row in rows), 2), round(sum(row["discount_amount"] for row in linked), 2),
                len(releasable), round(sum(row["discount_amount"] for row in releasable), 2), len(unlinked), round(sum(row["discount_amount"] for row in unlinked), 2), "金额优惠",
            ),
        )


def _insert_issues(db: sqlite3.Connection, calc_id: int, import_batch_id: int, coupons: list[dict], issues: list[tuple[str, str, str]], cutoff: str) -> None:
    for issue_type, level, reason in issues:
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, issue_type, level, reason),
        )
    unlinked = [row for row in coupons if row["order_id"] is None]
    dual = [row for row in unlinked if str(row["use_period"]).startswith("关联单据:") and "," in str(row["use_period"])]
    if dual:
        amount = round(sum(row["discount_amount"] for row in dual), 2)
        raw_numbers = [str(row["use_period"]).removeprefix("关联单据:") for row in dual]
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "返券双单号无法唯一归因", "警告", f"{len(dual)}张已用券关联多个订单号，金额{amount}元已计入实际发生，不能释放；原始单号={raw_numbers}"),
        )
    other = [row for row in unlinked if row not in dual]
    if other:
        amount = round(sum(row["discount_amount"] for row in other), 2)
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "返券单号未命中订单", "警告", f"{len(other)}张已用券没有唯一订单，金额{amount}元已计入实际发生，不能释放"),
        )
    unmatched = db.execute(
        """SELECT COUNT(*) FROM coupon_redemption c
           WHERE c.import_batch_id=? AND c.customer_no<>'' AND NOT EXISTS (
             SELECT 1 FROM customer k WHERE k.import_batch_id=c.import_batch_id AND k.customer_no=c.customer_no)""",
        (import_batch_id,),
    ).fetchone()[0]
    if unmatched:
        db.execute(
            "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
            (calc_id, None, "券领取客户未匹配", "警告", f"{unmatched}张券的领取客户未命中客户主数据"),
        )
    db.execute(
        "INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES(?,?,?,?,?)",
        (calc_id, None, "T-2释放口径", "提示", f"可释放要求订单状态为已完成，且下单时间≤{cutoff}。履约完成时间为空不否决释放。"),
    )


def _can_release(order: dict | None, cutoff: str) -> bool:
    if not order or order.get("status") != "已完成" or not order.get("order_time"):
        return False
    return _stamp(order["order_time"], "start") <= cutoff


def _stamp(value: str | None, edge: str) -> str:
    text = (value or "").strip()
    if len(text) == 10 and text[4:5] == "-" and text[7:8] == "-":
        return text + (" 00:00:00" if edge == "start" else " 23:59:59")
    return text


def _text_is_gift(activity_type: str | None, promo_method: str | None) -> bool:
    return "赠" in f"{activity_type or ''}{promo_method or ''}"
