"""旧的理论核算实验。费用平台导入不调用本模块。

导入 standard.xlsx 之后，产品链路使用 actual_result_calculator.calculate_actual_results。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import sqlite3


ZERO = Decimal("0.00")


def money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TemplateResult:
    theoretical_benefit: Decimal = ZERO
    actual_benefit: Decimal = ZERO
    gift_qty_entitled: Decimal | None = None
    gift_qty_actual: Decimal | None = None
    formula_ref: str = ""


@dataclass(frozen=True)
class CalculationSummary:
    template: str
    theoretical_benefit: Decimal
    actual_benefit: Decimal
    gift_qty_entitled: Decimal | None
    gift_qty_actual: Decimal | None
    release_candidates: int
    settle_amount: Decimal | None


def _parse(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _ensure_batch(connection: sqlite3.Connection, calc_batch_id: int, calc_date: str, rule_version: str) -> None:
    row = connection.execute("SELECT calc_batch_id FROM result_calc_batch WHERE calc_batch_id=?", (calc_batch_id,)).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO result_calc_batch(calc_batch_id,calc_date,rule_version,operator,created_at) VALUES (?,?,?,?,?)",
            (calc_batch_id, calc_date, rule_version or "unknown", "promotion_calculator", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )


def _template(activity: sqlite3.Row, connection: sqlite3.Connection) -> str:
    has_coupon_rules = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM coupon_issue_rule WHERE activity_id=?)", (activity["activity_id"],)
    ).fetchone()[0]
    if activity["activity_category"] == "券类" or has_coupon_rules:
        return "coupon"
    if "赠" in (activity["promotion_type"] or ""):
        return "gift"
    return "discount"


def _in_activity_window(activity: sqlite3.Row, order_time: object) -> bool:
    value = _parse(order_time)
    start, end = _parse(activity["start_time"]), _parse(activity["end_time"])
    return bool(value and start and end and start <= value <= end)


def _customer_hit(customer: sqlite3.Row, dimension: str, value: str) -> bool:
    customer_no, customer_type = customer[0] or "", customer[1] or ""
    if dimension in {"类型", "客户类型"}:
        return customer_type == value
    if dimension in {"客户编号", "编号"}:
        return customer_no == value
    return value in {customer_no, customer_type}


def _product_hit(product_no: str, brand: str, product_name: str, dimension: str, value: str) -> bool:
    if product_no.startswith("UNMATCHED:"):
        return False
    if dimension == "商品名称前缀":
        return bool(value) and product_name.startswith(value)
    if dimension == "商品名称":
        return product_name == value
    if dimension == "品牌":
        return brand == value
    if dimension in {"商品", "商品编号"}:
        return product_no == value
    return value in {product_no, brand}


def _grouped_scopes(connection: sqlite3.Connection, activity_id: int) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for category, dimension, value in connection.execute(
        "SELECT scope_category,scope_dimension,scope_value FROM activity_scope WHERE activity_id=?", (activity_id,)
    ):
        if category == "限购":
            continue
        grouped.setdefault((category or "", dimension or ""), []).append(value or "")
    return grouped


def _scope_matches(connection: sqlite3.Connection, activity_id: int, order_id: int) -> bool:
    """同一范围维度的多个取值满足一个即可；不同维度要同时满足。限购不参与入围。"""
    grouped = _grouped_scopes(connection, activity_id)
    if not grouped:
        return True
    customer = connection.execute(
        "SELECT c.platform_customer_no,c.customer_type FROM order_header oh LEFT JOIN customer c ON c.customer_id=oh.customer_id WHERE oh.order_id=?", (order_id,)
    ).fetchone()
    products = [
        (row[0] or "", row[1] or "", row[2] or "")
        for row in connection.execute(
            "SELECT p.platform_product_no,p.brand,p.product_name FROM order_line ol LEFT JOIN product p ON p.product_id=ol.product_id WHERE ol.order_id=?", (order_id,)
        )
    ]
    for (category, dimension), values in grouped.items():
        if category == "客户" and customer and not any(_customer_hit(customer, dimension, value) for value in values):
            return False
        if category == "禁用客户" and customer and any(_customer_hit(customer, dimension, value) for value in values):
            return False
        if category == "商品" and products and not any(_product_hit(*product, dimension, value) for product in products for value in values):
            return False
        if category == "禁用商品" and any(_product_hit(*product, dimension, value) for product in products for value in values):
            return False
    return True


def _per_customer_limit(connection: sqlite3.Connection, activity_id: int) -> int | None:
    row = connection.execute(
        "SELECT scope_value FROM activity_scope WHERE activity_id=? AND scope_category='限购' AND scope_dimension='每客户次数' ORDER BY scope_id LIMIT 1",
        (activity_id,),
    ).fetchone()
    if row is None or str(row[0] or "").strip() == "":
        return None
    return int(Decimal(str(row[0])))


def _derive_gift_participation(connection: sqlite3.Connection, activity: sqlite3.Row) -> None:
    """没有活动核销明细时，按规则、范围和订单行生成参加名单。已有名单的活动不补订单。"""
    activity_id = activity["activity_id"]
    if connection.execute("SELECT COUNT(*) FROM order_activity WHERE activity_id=?", (activity_id,)).fetchone()[0]:
        return
    rule = connection.execute("SELECT * FROM activity_rule WHERE activity_id=? ORDER BY tier_no, rule_id LIMIT 1", (activity_id,)).fetchone()
    if rule is None:
        return
    benefit = connection.execute(
        "SELECT gift_product_no, gift_product_name FROM activity_rule_benefit WHERE rule_id=? AND benefit_type='赠品' LIMIT 1", (rule["rule_id"],)
    ).fetchone()
    gift_no = (benefit["gift_product_no"] or "") if benefit else ""
    gift_name = (benefit["gift_product_name"] or "") if benefit else ""
    threshold = money(rule["threshold_value"])
    product_scopes = [
        (dimension, values)
        for (category, dimension), values in _grouped_scopes(connection, activity_id).items()
        if category == "商品"
    ]
    buckets: dict[int, dict[str, Decimal]] = {}
    for row in connection.execute(
        """SELECT oh.order_id, p.platform_product_no, p.brand, p.product_name, ol.order_qty, ol.pre_discount_amount
           FROM order_header oh JOIN order_line ol ON ol.order_id=oh.order_id
           LEFT JOIN product p ON p.product_id=ol.product_id
           WHERE oh.dealer_platform_id=? AND oh.order_time>=? AND oh.order_time<=?""",
        (activity["dealer_platform_id"], activity["start_time"], activity["end_time"]),
    ):
        bucket = buckets.setdefault(row["order_id"], {"amount": ZERO, "gift": ZERO})
        product_no, brand, product_name = row["platform_product_no"] or "", row["brand"] or "", row["product_name"] or ""
        if product_no.startswith("UNMATCHED:"):
            continue
        is_gift = (gift_name and product_name == gift_name) or (gift_no and product_no == gift_no)
        if is_gift:
            bucket["gift"] += money(row["order_qty"])
            continue
        if _line_in_scopes(product_no, brand, product_name, product_scopes):
            bucket["amount"] += money(row["pre_discount_amount"])
    for order_id, bucket in buckets.items():
        if bucket["amount"] < threshold and bucket["gift"] <= ZERO:
            continue
        if bucket["amount"] >= threshold and not _scope_matches(connection, activity_id, order_id) and bucket["gift"] <= ZERO:
            continue
        connection.execute(
            "INSERT INTO order_activity(order_id, activity_id, rule_id, activity_product_amount, platform_actual_benefit, gift_qty_actual) VALUES(?,?,?,?,?,?)",
            (order_id, activity_id, rule["rule_id"], str(bucket["amount"]), "0.00", str(bucket["gift"])),
        )


def _line_in_scopes(product_no: str, brand: str, product_name: str, product_scopes: list[tuple[str, list[str]]]) -> bool:
    if not product_scopes:
        return True
    return all(any(_product_hit(product_no, brand, product_name, dimension, value) for value in values) for dimension, values in product_scopes)


def calculate_discount(rule: sqlite3.Row, order_activity: sqlite3.Row, qualifies: bool) -> TemplateResult:
    theoretical = money(rule["reduce_amount"]) if qualifies and money(order_activity["activity_product_amount"]) >= money(rule["threshold_value"]) else ZERO
    return TemplateResult(theoretical, money(order_activity["platform_actual_benefit"]), formula_ref="activity_rule.reduce_amount")


def calculate_gift(connection: sqlite3.Connection, rule: sqlite3.Row, order_activity: sqlite3.Row, qualifies: bool) -> TemplateResult:
    benefit = connection.execute("SELECT gift_qty FROM activity_rule_benefit WHERE rule_id=? AND benefit_type='赠品'", (rule["rule_id"],)).fetchone()
    entitled = money(benefit[0]) if benefit and qualifies and money(order_activity["activity_product_amount"]) >= money(rule["threshold_value"]) else ZERO
    return TemplateResult(ZERO, money(order_activity["platform_actual_benefit"]), entitled, money(order_activity["gift_qty_actual"]), "activity_rule_benefit.gift_qty")


def calculate_coupon(connection: sqlite3.Connection, activity_id: int, rule: sqlite3.Row, order_activity: sqlite3.Row, qualifies: bool, order_no: str) -> TemplateResult:
    ledger = connection.execute(
        "SELECT cl.*, cir.issue_mode,cir.issue_start_at,cir.issue_end_at,cir.auto_issue_at,cir.max_claim_per_customer,cur.use_start_at,cur.use_end_at,cur.validity_mode,cur.valid_days_after_receive FROM coupon_ledger cl JOIN coupon_issue_rule cir ON cir.activity_id=cl.activity_id JOIN coupon_use_rule cur ON cur.activity_id=cl.activity_id WHERE cl.activity_id=? AND cl.use_order_no=?",
        (activity_id, order_no),
    ).fetchone()
    if ledger is None or ledger["coupon_status"] != "已使用" or not qualifies:
        return TemplateResult(formula_ref="coupon_ledger eligibility")
    receive, use = _parse(ledger["receive_time"]), _parse(ledger["use_time"])
    order_rebate = ledger["issue_mode"] == "order_rebate"
    if not order_rebate and (not receive or not use):
        return TemplateResult(formula_ref="coupon_ledger timing")
    issue_start, issue_end, auto_at = _parse(ledger["issue_start_at"]), _parse(ledger["issue_end_at"]), _parse(ledger["auto_issue_at"])
    if ledger["issue_mode"] == "auto_grant" and (not auto_at or receive < auto_at):
        return TemplateResult(formula_ref="coupon auto issue timing")
    if ledger["issue_mode"] == "manual_claim" and (not issue_start or receive < issue_start or (issue_end and receive > issue_end)):
        return TemplateResult(formula_ref="coupon manual claim timing")
    use_start, use_end = _parse(ledger["use_start_at"]), _parse(ledger["use_end_at"])
    if receive and use and ledger["validity_mode"] == "fixed_period" and (not use_start or not use_end or not (use_start <= use <= use_end)):
        return TemplateResult(formula_ref="coupon use timing")
    if receive and use and ledger["validity_mode"] == "days_after_receive" and use > receive + timedelta(days=int(ledger["valid_days_after_receive"] or 0)):
        return TemplateResult(formula_ref="coupon use timing")
    amount = money(rule["reduce_amount"])
    if amount == ZERO:
        amount = money(ledger["discount_amount"])
    if money(order_activity["activity_product_amount"]) < money(rule["threshold_value"]):
        amount = ZERO
    return TemplateResult(amount, money(ledger["discount_amount"]), formula_ref="coupon_issue_rule + coupon_use_rule + coupon_ledger")


def calculate_activity(connection: sqlite3.Connection, activity_id: int, calc_batch_id: int, calc_date: str) -> CalculationSummary:
    connection.row_factory = sqlite3.Row
    activity = connection.execute("SELECT * FROM activity WHERE activity_id=?", (activity_id,)).fetchone()
    if activity is None:
        raise KeyError(activity_id)
    _ensure_batch(connection, calc_batch_id, calc_date, activity["rule_version"])
    template = _template(activity, connection)
    if template == "gift":
        _derive_gift_participation(connection, activity)
    limit = _per_customer_limit(connection, activity_id) if template == "gift" else None
    granted: dict[object, int] = {}
    rows = connection.execute(
        """SELECT oa.*,oh.order_no,oh.order_time,oh.order_status,oh.customer_id
           FROM order_activity oa JOIN order_header oh ON oh.order_id=oa.order_id
           WHERE oa.activity_id=? ORDER BY oh.customer_id, oh.order_time, oh.order_id""",
        (activity_id,),
    ).fetchall()
    total_theoretical = total_actual = ZERO
    total_gift_entitled = total_gift_actual = ZERO
    candidates = 0
    released_amount = ZERO
    calc_at = _parse(calc_date) or datetime.now()
    for row in rows:
        rule = connection.execute("SELECT * FROM activity_rule WHERE rule_id=?", (row["rule_id"],)).fetchone()
        if rule is None:
            connection.execute("INSERT INTO result_quality_issue(order_no,issue_type,level,reason,evidence_ref,calc_batch_id) VALUES (?,?,?,?,?,?)", (row["order_no"], "活动规则缺失", "警告", "order_activity 未关联有效 activity_rule", "order_activity", calc_batch_id))
            continue
        qualifies = _in_activity_window(activity, row["order_time"]) and _scope_matches(connection, activity_id, row["order_id"])
        result = calculate_discount(rule, row, qualifies) if template == "discount" else calculate_gift(connection, rule, row, qualifies) if template == "gift" else calculate_coupon(connection, activity_id, rule, row, qualifies, row["order_no"])
        if limit is not None and result.gift_qty_entitled is not None and result.gift_qty_entitled > ZERO:
            customer_key = row["customer_id"] if row["customer_id"] is not None else row["order_id"]
            if granted.get(customer_key, 0) >= limit:
                result = TemplateResult(result.theoretical_benefit, result.actual_benefit, ZERO, result.gift_qty_actual, result.formula_ref)
            else:
                granted[customer_key] = granted.get(customer_key, 0) + 1
        consistency = "一致" if (result.gift_qty_entitled is not None and result.gift_qty_entitled == result.gift_qty_actual) or (result.gift_qty_entitled is None and result.theoretical_benefit == result.actual_benefit) else "差异"
        diff = (result.gift_qty_actual - result.gift_qty_entitled) if result.gift_qty_entitled is not None else result.actual_benefit - result.theoretical_benefit
        connection.execute("DELETE FROM result_entitlement WHERE order_activity_id=? AND calc_batch_id=?", (row["order_activity_id"], calc_batch_id))
        connection.execute("INSERT INTO result_entitlement(order_activity_id,theoretical_benefit,platform_actual_benefit,gift_qty_entitled,gift_qty_actual,consistency,diff_amount,formula_ref,calc_batch_id) VALUES (?,?,?,?,?,?,?,?,?)", (row["order_activity_id"], str(result.theoretical_benefit), str(result.actual_benefit), str(result.gift_qty_entitled) if result.gift_qty_entitled is not None else None, str(result.gift_qty_actual) if result.gift_qty_actual is not None else None, consistency, str(diff), result.formula_ref, calc_batch_id))
        eligible_release = row["order_status"] == "已完成" and _parse(row["order_time"]) is not None and _parse(row["order_time"]) <= calc_at - timedelta(days=2)
        connection.execute("INSERT OR REPLACE INTO result_release_candidate(order_id,calc_date,is_candidate,reason,calc_batch_id) VALUES (?,?,?,?,?)", (row["order_id"], calc_date, int(eligible_release), "已完成且达到T-2" if eligible_release else "未达释放节点", calc_batch_id))
        if consistency != "一致":
            reason = f"应赠={result.gift_qty_entitled};实赠={result.gift_qty_actual}" if result.gift_qty_entitled is not None else f"理论={result.theoretical_benefit};实际={result.actual_benefit}"
            connection.execute("INSERT INTO result_quality_issue(order_no,issue_type,level,reason,evidence_ref,calc_batch_id) VALUES (?,?,?,?,?,?)", (row["order_no"], "理论权益与实际执行不一致", "警告", reason, result.formula_ref, calc_batch_id))
        elif not eligible_release:
            connection.execute("INSERT INTO result_quality_issue(order_no,issue_type,level,reason,evidence_ref,calc_batch_id) VALUES (?,?,?,?,?,?)", (row["order_no"], "未达释放节点", "提示", "订单未完成或尚未达到T-2", "fulfillment", calc_batch_id))
        total_theoretical += result.theoretical_benefit
        total_actual += result.actual_benefit
        total_gift_entitled += result.gift_qty_entitled or ZERO
        total_gift_actual += result.gift_qty_actual or ZERO
        if eligible_release and consistency == "一致":
            candidates += 1
            released_amount += result.actual_benefit
    connection.execute("DELETE FROM result_fee WHERE activity_id=? AND calc_batch_id=?", (activity_id, calc_batch_id))
    if template != "gift" and (template != "coupon" or total_actual > ZERO):
        tpm = connection.execute("SELECT * FROM tpm_application WHERE tpm_id=?", (activity["tpm_id"],)).fetchone() if activity["tpm_id"] else None
        connection.execute("INSERT INTO result_fee(tpm_id,activity_id,actual_discount_total,gift_cost_total,fee_bearer,settle_target,budget_amount,budget_reserve_no,settle_amount,diff_amount,settle_status,calc_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (activity["tpm_id"], activity_id, str(total_actual), None, tpm["fee_pay_dept"] if tpm else None, None, tpm["apply_amount"] if tpm else None, tpm["budget_reserve_no"] if tpm else None, str(released_amount), str(money(tpm["apply_amount"]) - released_amount) if tpm else None, "待结算" if candidates else "待确认", calc_batch_id))
    elif template == "gift":
        connection.execute("INSERT INTO result_fee(tpm_id,activity_id,actual_discount_total,gift_cost_total,fee_bearer,settle_target,budget_amount,budget_reserve_no,settle_amount,diff_amount,settle_status,calc_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (None, activity_id, "0.00", None, None, None, None, None, None, None, "按赠品数量统计(不结算单价)", calc_batch_id))
    connection.commit()
    return CalculationSummary(template, total_theoretical, total_actual, total_gift_entitled if template == "gift" else None, total_gift_actual if template == "gift" else None, candidates, released_amount if template != "gift" else None)
