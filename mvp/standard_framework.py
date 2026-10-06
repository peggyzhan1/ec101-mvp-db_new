"""把标准工作簿装进 promotion_calculator 已经会读的表，再调用原框架。

标准表的范围、门槛、赠品和券核销原样装入。发放方式「下单返券」对应框架的 order_rebate。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from mvp.scripts.promotion_calculator import CalculationSummary, calculate_activity

DDL = Path(__file__).resolve().parent / "ddl" / "ec101_mvp_sqlite.sql"
ISSUE_MODES = {
    "auto_grant": "auto_grant", "manual_claim": "manual_claim", "order_rebate": "order_rebate",
    "自动发放": "auto_grant", "手动领取": "manual_claim", "下单返券": "order_rebate",
}
VALIDITY_MODES = {"fixed_period": "fixed_period", "days_after_receive": "days_after_receive", "固定期间": "fixed_period", "领取后有效天数": "days_after_receive"}


@dataclass
class PreparedActivity:
    name: str
    activity_id: int
    kind: str
    order_count: int
    notes: list[str] = field(default_factory=list)


def open_calculator_db(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:" if path is None else path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(DDL.read_text(encoding="utf-8"))
    return connection


def _num(value: object) -> float:
    text = "" if value is None else str(value).strip()
    if not text:
        return 0.0
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def _category(activity_type: str) -> str:
    return "券类" if "券" in activity_type else "非券类"


def load_standard_tables(connection: sqlite3.Connection, tables: dict[str, list[dict[str, str]]], dealer_name: str, platform_name: str) -> list[PreparedActivity]:
    dealer_id = connection.execute(
        "INSERT INTO dealer_platform(dealer_name, platform_name) VALUES(?,?)",
        (dealer_name, platform_name),
    ).lastrowid
    customer_ids: dict[str, int] = {}
    for row in tables.get("标准客户", []):
        customer_no = row.get("客户编号", "").strip()
        if not customer_no or customer_no in customer_ids:
            continue
        customer_ids[customer_no] = connection.execute(
            "INSERT INTO customer(dealer_platform_id, platform_customer_no, customer_name, customer_type) VALUES(?,?,?,?)",
            (dealer_id, customer_no, row.get("客户名称", ""), row.get("客户类型", "")),
        ).lastrowid
    product_ids: dict[str, int] = {}
    for row in tables.get("标准商品", []):
        product_no = row.get("商品编号", "").strip()
        if not product_no or product_no in product_ids:
            continue
        product_ids[product_no] = connection.execute(
            "INSERT INTO product(dealer_platform_id, platform_product_no, product_name, brand) VALUES(?,?,?,?)",
            (dealer_id, product_no, row.get("商品名称", ""), row.get("商品品牌", "")),
        ).lastrowid
    order_ids: dict[str, int] = {}
    quantities: dict[tuple[int, int], list[float]] = {}
    for row in tables.get("标准订单明细", []):
        order_no = row.get("单据编号", "").strip()
        product_no = row.get("商品编号", "").strip()
        if not order_no or not product_no:
            continue
        if product_no not in product_ids:
            product_ids[product_no] = connection.execute(
                "INSERT INTO product(dealer_platform_id, platform_product_no, product_name, brand) VALUES(?,?,?,?)",
                (dealer_id, product_no, row.get("商品名称", ""), ""),
            ).lastrowid
        if order_no not in order_ids:
            order_ids[order_no] = connection.execute(
                "INSERT INTO order_header(dealer_platform_id, order_no, order_time, customer_id, order_status) VALUES(?,?,?,?,?)",
                (dealer_id, order_no, row.get("下单时间") or "1900-01-01 00:00:00", customer_ids.get(row.get("客户编号", "").strip()), row.get("订单状态") or "未知"),
            ).lastrowid
        key = (order_ids[order_no], product_ids[product_no])
        current = quantities.setdefault(key, [0.0, 0.0])
        current[0] += _num(row.get("数量"))
        current[1] += _num(row.get("优惠前金额"))
    connection.executemany(
        "INSERT INTO order_line(order_id, product_id, order_qty, pre_discount_amount) VALUES(?,?,?,?)",
        [(order_id, product_id, qty, amount) for (order_id, product_id), (qty, amount) in quantities.items()],
    )
    prepared = [_load_activity(connection, dealer_id, tables, row, order_ids) for row in tables.get("标准活动", [])]
    prepared.extend(_load_coupon(connection, dealer_id, tables, order_ids, customer_ids))
    return prepared


def _load_activity(connection: sqlite3.Connection, dealer_id: int, tables: dict[str, list[dict[str, str]]], row: dict[str, str], order_ids: dict[str, int]) -> PreparedActivity:
    activity_no = row.get("活动编号", "").strip()
    activity_id = connection.execute(
        "INSERT INTO activity(dealer_platform_id, activity_name, activity_category, promotion_type, start_time, end_time, activity_status, rule_version) VALUES(?,?,?,?,?,?,?,?)",
        (dealer_id, row.get("活动名称", ""), _category(row.get("活动类型", "")), row.get("促销方式") or row.get("活动类型", ""), row.get("开始时间") or "1900-01-01 00:00:00", row.get("结束时间") or "1900-01-01 00:00:00", row.get("活动状态", ""), "standard.xlsx"),
    ).lastrowid
    rule_ids: dict[str, int] = {}
    for rule in tables.get("标准活动规则", []):
        if rule.get("活动编号", "").strip() != activity_no:
            continue
        rule_ids[rule.get("规则编号", "").strip()] = connection.execute(
            "INSERT INTO activity_rule(activity_id, tier_no, threshold_type, threshold_value, reduce_amount) VALUES(?,?,?,?,?)",
            (activity_id, len(rule_ids) + 1, rule.get("门槛类型", ""), _num(rule.get("门槛值")), _num(rule.get("立减金额"))),
        ).lastrowid
    gift_names: set[str] = set()
    for benefit in tables.get("标准活动权益", []):
        if benefit.get("活动编号", "").strip() != activity_no:
            continue
        rule_id = rule_ids.get(benefit.get("规则编号", "").strip()) or next(iter(rule_ids.values()), None)
        if rule_id is None:
            continue
        gift_name = benefit.get("赠品商品名称", "").strip()
        if benefit.get("权益类型") == "赠品" and gift_name:
            gift_names.add(gift_name)
        connection.execute(
            "INSERT INTO activity_rule_benefit(rule_id, benefit_type, gift_product_no, gift_product_name, gift_qty) VALUES(?,?,?,?,?)",
            (rule_id, benefit.get("权益类型", ""), benefit.get("赠品商品编号", ""), gift_name, _num(benefit.get("赠品数量")) or None),
        )
    for scope in tables.get("标准活动范围", []):
        if scope.get("活动编号", "").strip() != activity_no:
            continue
        connection.execute(
            "INSERT INTO activity_scope(activity_id, scope_category, scope_dimension, scope_value) VALUES(?,?,?,?)",
            (activity_id, scope.get("范围类别", ""), scope.get("范围维度", ""), scope.get("范围值", "")),
        )
    default_rule = next(iter(rule_ids.values()), None)
    loaded = skipped = 0
    for execution in tables.get("标准活动核销明细", []):
        if execution.get("活动编号", "").strip() != activity_no:
            continue
        order_id = order_ids.get(execution.get("订单号", "").strip())
        if order_id is None:
            skipped += 1
            continue
        gift_qty = _gift_qty(connection, order_id, gift_names) if gift_names else None
        connection.execute(
            "INSERT INTO order_activity(order_id, activity_id, rule_id, activity_product_amount, platform_actual_benefit, gift_qty_actual) VALUES(?,?,?,?,?,?)",
            (order_id, activity_id, default_rule, _num(execution.get("商品总金额")), _num(execution.get("优惠金额")), gift_qty),
        )
        loaded += 1
    notes = [f"标准活动核销明细写入 {loaded} 笔"]
    if skipped:
        notes.append(f"{skipped} 笔核销明细的订单号在标准订单里不存在")
    if not loaded:
        notes.append("核销明细是空的。满赠由框架按活动规则、范围和订单行确定参加订单")
    return PreparedActivity(row.get("活动名称", activity_no), activity_id, "活动", loaded, notes)


def _gift_qty(connection: sqlite3.Connection, order_id: int, gift_names: set[str]) -> float:
    marks = ",".join("?" * len(gift_names))
    total = connection.execute(
        f"""SELECT COALESCE(SUM(ol.order_qty),0) FROM order_line ol
            JOIN product p ON p.product_id=ol.product_id
            WHERE ol.order_id=? AND p.product_name IN ({marks})""",
        (order_id, *gift_names),
    ).fetchone()[0]
    return round(float(total or 0), 2)


def _load_coupon(connection: sqlite3.Connection, dealer_id: int, tables: dict[str, list[dict[str, str]]], order_ids: dict[str, int], customer_ids: dict[str, int]) -> list[PreparedActivity]:
    prepared: list[PreparedActivity] = []
    for config in tables.get("标准优惠券配置", []):
        config_no = config.get("优惠券配置编号", "").strip()
        issue = next((row for row in tables.get("标准优惠券发放规则", []) if row.get("优惠券配置编号", "").strip() == config_no), {})
        use = next((row for row in tables.get("标准优惠券使用规则", []) if row.get("优惠券配置编号", "").strip() == config_no), {})
        activity_id = connection.execute(
            "INSERT INTO activity(dealer_platform_id, activity_name, activity_category, promotion_type, start_time, end_time, activity_status, rule_version) VALUES(?,?,?,?,?,?,?,?)",
            (dealer_id, config.get("优惠券名称", config_no), "券类", config.get("券类型") or "优惠券", issue.get("发放开始时间") or "1900-01-01 00:00:00", issue.get("发放结束时间") or "1900-01-01 00:00:00", config.get("配置状态", ""), "standard.xlsx"),
        ).lastrowid
        rule_id = connection.execute(
            "INSERT INTO activity_rule(activity_id, tier_no, threshold_type, threshold_value, reduce_amount) VALUES(?,?,?,?,?)",
            (activity_id, 1, "金额", 0, 0),
        ).lastrowid
        notes = ["券配置没有单独的立减金额时，理论金额使用核销明细上的优惠金额"]
        issue_mode = ISSUE_MODES.get(issue.get("发放方式", "").strip())
        validity_mode = VALIDITY_MODES.get(use.get("有效期类型", "").strip())
        if issue_mode and validity_mode:
            connection.execute(
                "INSERT INTO coupon_issue_rule(activity_id, issue_mode, issue_start_at, issue_end_at, auto_issue_at, coupon_qty_per_grant, max_claim_per_customer, daily_claim_limit, rule_status) VALUES(?,?,?,?,?,?,?,?,?)",
                (activity_id, issue_mode, issue.get("发放开始时间") or "1900-01-01 00:00:00", issue.get("发放结束时间") or None, issue.get("自动发放时间") or None, _num(issue.get("每次发放数量")) or 1, _num(issue.get("每客户领取上限")) or None, _num(issue.get("每日领取上限")) or None, issue.get("规则状态") or "已结束"),
            )
            connection.execute(
                "INSERT INTO coupon_use_rule(activity_id, coupon_type, validity_mode, use_start_at, use_end_at, valid_days_after_receive, max_use_per_coupon, rule_status) VALUES(?,?,?,?,?,?,?,?)",
                (activity_id, use.get("券类型") or config.get("券类型") or "优惠券", validity_mode, use.get("使用开始时间") or None, use.get("使用结束时间") or None, int(_num(use.get("领取后有效天数"))) or None, _num(use.get("每张券最多使用次数")) or 1, use.get("规则状态") or "已结束"),
            )
        else:
            if not issue_mode:
                notes.append(f"发放方式「{issue.get('发放方式', '')}」不是自动发放、手动领取或下单返券，发券规则没有写入")
            if not validity_mode:
                notes.append(f"有效期类型「{use.get('有效期类型', '')}」不是框架接受的固定期间或领取后有效天数，使用规则没有写入")
            if issue_mode or validity_mode:
                notes.append("框架要发放规则和使用规则同时存在，缺一边就不会按券计算金额")
        linked = skipped = blank_time = 0
        seen_orders: set[int] = set()
        for redemption in tables.get("标准优惠券核销明细", []):
            order_no = redemption.get("订单号", "").strip()
            order_id = order_ids.get(order_no)
            if not order_no or order_id is None:
                skipped += 1
                continue
            if not redemption.get("领取时间", "").strip() or not redemption.get("使用时间", "").strip():
                blank_time += 1
            if order_id not in seen_orders:
                connection.execute(
                    "INSERT INTO order_activity(order_id, activity_id, rule_id, activity_product_amount, platform_actual_benefit, gift_qty_actual) VALUES(?,?,?,?,?,NULL)",
                    (order_id, activity_id, rule_id, 0, _num(redemption.get("优惠金额"))),
                )
                seen_orders.add(order_id)
            connection.execute(
                "INSERT INTO coupon_ledger(dealer_platform_id, activity_id, coupon_no, coupon_name, customer_id, receive_time, coupon_status, use_time, use_order_no, discount_amount) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (dealer_id, activity_id, redemption.get("优惠券编号", ""), config.get("优惠券名称", ""), customer_ids.get(redemption.get("客户编号", "").strip()), redemption.get("领取时间") or None, redemption.get("状态", ""), redemption.get("使用时间") or None, order_no, _num(redemption.get("优惠金额"))),
            )
            linked += 1
        notes.append(f"核销明细里写了订单号的券 {linked} 张，没有唯一订单号的 {skipped} 张不进入框架")
        if blank_time:
            notes.append(f"其中 {blank_time} 张领取时间或使用时间是空的。下单返券不依赖这两列，金额用优惠金额")
        prepared.append(PreparedActivity(config.get("优惠券名称", config_no), activity_id, "优惠券", len(seen_orders), notes))
    return prepared


def calculate_standard_tables(connection: sqlite3.Connection, tables: dict[str, list[dict[str, str]]], dealer_name: str, platform_name: str, calc_date: str) -> list[tuple[PreparedActivity, CalculationSummary]]:
    prepared = load_standard_tables(connection, tables, dealer_name, platform_name)
    connection.execute(
        "INSERT INTO result_calc_batch(calc_date, rule_version, operator, created_at) VALUES(?,?,?,?)",
        (calc_date, "standard.xlsx", "promotion_calculator", calc_date + " 00:00:00"),
    )
    batch_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    return [(item, calculate_activity(connection, item.activity_id, batch_id, calc_date)) for item in prepared]


def money_text(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"
