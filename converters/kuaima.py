"""快马 source files -> reviewed standard workbook."""

from __future__ import annotations

import re
from collections import defaultdict

from .common import ConversionRequest, ConversionResult, add_activity_inputs, add_coupon_inputs, date_value, empty_tables, finish_conversion, index_header, number_value, source_rows, value
from mvp.scripts.readers import to_num


# 快马活动明细的"享受促销政策"形如 "参与[可口可乐满减]组合金额满¥300，立减¥15活动，为您节省¥1.24"。
POLICY_ACTIVITY_PATTERN = re.compile(r"参与\[(?P<name>[^\]]+)\]")


def parse_policy_activity_name(policy_text: str) -> str:
    """Return the platform activity name embedded in a 快马 policy sentence, or the sentence itself."""
    text = (policy_text or "").strip()
    match = POLICY_ACTIVITY_PATTERN.search(text)
    return match.group("name").strip() if match else text


def infer_activity_type(policy_text: str, activity_name: str) -> str:
    text = f"{activity_name} {policy_text}"
    if "赠" in text:
        return "满赠"
    if "减" in text:
        return "满减"
    return "其他"


def _join_numbers(numbers: list[str]) -> str:
    return ";".join(sorted({number for number in numbers if number}))


def convert_kuaima(request: ConversionRequest) -> ConversionResult:
    tables = empty_tables()
    order_lookup: dict[str, dict[str, str]] = {}
    for path in request.source_paths.get("customer", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            customer_no = value(row, indexes, "客户编号")
            if customer_no:
                tables["标准客户"].append({
                    "客户编号": customer_no, "客户名称": value(row, indexes, "客户名称"), "客户类型": value(row, indexes, "客户类型"),
                    "客户区域": value(row, indexes, "客户区域"), "详细地址": value(row, indexes, "详细地址"),
                    "联系电话": value(row, indexes, "联系电话"), "添加时间": date_value(value(row, indexes, "添加时间")),
                    "所属业务员": value(row, indexes, "所属业务员"),
                })
    for path in request.source_paths.get("product", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            product_no = value(row, indexes, "商品编号")
            if product_no:
                tables["标准商品"].append({
                    "商品编号": product_no, "商品名称": value(row, indexes, "商品名称"), "商品品牌": value(row, indexes, "品牌"),
                    "商品目录": value(row, indexes, "一级目录"), "商品条码": value(row, indexes, "条形码"),
                    "商品规格": value(row, indexes, "规格值1"), "基本单位": value(row, indexes, "单位"),
                    "箱规": value(row, indexes, "换算关系1"), "每箱基本单位数量": number_value(value(row, indexes, "换算关系1")),
                })
    for path in request.source_paths.get("order_detail", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            order_no = value(row, indexes, "订单编号")
            if not order_no:
                continue
            record = {
                "单据编号": order_no, "下单时间": date_value(value(row, indexes, "下单时间")),
                "客户编号": value(row, indexes, "客户编号"), "客户名称": value(row, indexes, "客户名称"),
                "商品编号": value(row, indexes, "商品编号"), "商品名称": value(row, indexes, "商品名称"),
                "商品目录": value(row, indexes, "商品目录"), "规格": value(row, indexes, "规格"),
                "商品条码": value(row, indexes, "商品条码"), "单位": value(row, indexes, "订货数量单位"),
                "数量": number_value(value(row, indexes, "订货数量")), "优惠前金额": number_value(value(row, indexes, "优惠前金额")),
                "活动编号": "", "优惠券编号": "", "优惠金额": number_value(value(row, indexes, "优惠金额")),
                "实付金额": number_value(value(row, indexes, "订货金额")), "业务员": value(row, indexes, "所属业务员"),
                "订单来源": value(row, indexes, "订单来源"), "订单类型": value(row, indexes, "订单类型"),
                "订单状态": value(row, indexes, "订单状态"), "支付方式": value(row, indexes, "支付方式"),
                "下游订单编号": "", "单价": number_value(value(row, indexes, "订货单价")), "退货数量": "",
            }
            tables["标准订单明细"].append(record)
            order_lookup.setdefault(order_no, record)
    # 快马历史导出偶尔只在订单明细中带商品编号；补齐最小商品主数据，避免订单成为孤儿。
    known_products = {row["商品编号"] for row in tables["标准商品"]}
    for record in tables["标准订单明细"]:
        product_no = record["商品编号"]
        if product_no and product_no not in known_products:
            tables["标准商品"].append({
                "商品编号": product_no, "商品名称": record["商品名称"], "商品品牌": "", "商品目录": record["商品目录"],
                "商品条码": record["商品条码"], "商品规格": record["规格"], "基本单位": record["单位"], "箱规": "", "每箱基本单位数量": "",
            })
            known_products.add(product_no)

    # 活动明细是商品行级分摊：同一订单多行，每行一份"促销优惠金额"。核销按 订单 × 活动 聚合，
    # 活动名取自平台政策文本中的 [活动名]；手工活动配置（如提供）只用于把活动名映射到活动编号。
    configured = {str(item.get("活动名称", "") or ""): item for item in request.activity_inputs}
    execution: dict[tuple[str, str], dict[str, object]] = {}
    unparsed_rows = 0
    for path in request.source_paths.get("activity_execution", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            order_no = value(row, indexes, "订单号")
            if not order_no:
                continue
            policy = value(row, indexes, "享受促销政策")
            activity_name = parse_policy_activity_name(policy)
            if not activity_name:
                unparsed_rows += 1
                continue
            config = configured.get(activity_name, {})
            activity_no = str(config.get("活动编号", "") or "") or activity_name
            order = order_lookup.get(order_no, {})
            entry = execution.setdefault((order_no, activity_no), {
                "活动编号": activity_no, "活动名称": activity_name,
                "客户编号": order.get("客户编号", ""), "客户": order.get("客户名称", "") or value(row, indexes, "客户"),
                "所属业务员": order.get("业务员", ""), "订单号": order_no,
                "商品总金额": 0.0, "优惠金额": 0.0, "政策文本": policy,
            })
            entry["商品总金额"] += to_num(value(row, indexes, "商品总金额")) or 0.0
            entry["优惠金额"] += to_num(value(row, indexes, "促销优惠金额")) or 0.0
    for entry in execution.values():
        tables["标准活动核销明细"].append({
            "活动编号": entry["活动编号"], "活动名称": entry["活动名称"], "客户编号": entry["客户编号"], "客户": entry["客户"],
            "所属业务员": entry["所属业务员"], "订单号": entry["订单号"],
            "商品总金额": number_value(f"{entry['商品总金额']:.4f}"), "优惠金额": number_value(f"{entry['优惠金额']:.4f}"),
        })

    add_activity_inputs(tables, request.activity_inputs)
    configured_numbers = {row["活动编号"] for row in tables["标准活动"]}
    for entry in execution.values():
        if entry["活动编号"] in configured_numbers:
            continue
        configured_numbers.add(entry["活动编号"])
        tables["标准活动"].append({
            "活动编号": entry["活动编号"], "活动名称": entry["活动名称"],
            "活动类型": infer_activity_type(str(entry["政策文本"]), str(entry["活动名称"])), "促销方式": "",
            "开始时间": "", "结束时间": "", "是否允许叠加活动": "", "是否允许叠加优惠券": "", "活动状态": "",
        })

    for path in request.source_paths.get("coupon_redemption", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            coupon_no = value(row, indexes, "优惠券编号")
            if coupon_no:
                tables["标准优惠券核销明细"].append({
                    "优惠券编号": coupon_no, "客户编号": value(row, indexes, "客户编号"), "客户": value(row, indexes, "领取人"),
                    "所属业务员": value(row, indexes, "所属业务员"), "领取时间": date_value(value(row, indexes, "领取时间")),
                    "使用期限": value(row, indexes, "使用期限"), "状态": value(row, indexes, "状态"),
                    "使用时间": date_value(value(row, indexes, "使用时间")), "订单号": value(row, indexes, "使用订单号"),
                    "优惠金额": number_value(value(row, indexes, "优惠金额")),
                })

    # 订单行上的活动编号 / 优惠券编号只回填平台明细里明确记录过的，仅供展示与追溯，不参与核算。
    activities_by_order: dict[str, list[str]] = defaultdict(list)
    for (order_no, activity_no) in execution:
        activities_by_order[order_no].append(activity_no)
    coupons_by_order: dict[str, list[str]] = defaultdict(list)
    for coupon in tables["标准优惠券核销明细"]:
        if coupon["订单号"]:
            coupons_by_order[coupon["订单号"]].append(coupon["优惠券编号"])
    for record in tables["标准订单明细"]:
        record["活动编号"] = _join_numbers(activities_by_order.get(record["单据编号"], []))
        record["优惠券编号"] = _join_numbers(coupons_by_order.get(record["单据编号"], []))

    for order_no, order in order_lookup.items():
        tables["标准履约"].append({"单据编号": order_no, "下游订单编号": "", "履约订单状态": order.get("订单状态", ""), "出库时间": "", "完成时间": "", "结款状态": "", "退货数量": ""})
    add_coupon_inputs(tables, request.coupon_inputs)
    activity_summary = ", ".join(
        f"{name}:{sum(1 for (_, no) in execution if no == number)}单/{sum(float(e['优惠金额']) for (_, no), e in execution.items() if no == number):.2f}元"
        for number, name in sorted({(e["活动编号"], e["活动名称"]) for e in execution.values()})
    )
    return finish_conversion(request, tables, [
        "platform=快马", f"orders={len(order_lookup)}", f"activity_execution_rows={len(execution)}",
        f"activities={activity_summary or '无'}", f"unparsed_policy_rows={unparsed_rows}",
    ])
