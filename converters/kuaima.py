"""快马 source files -> reviewed standard workbook."""

from __future__ import annotations

from collections import defaultdict

from .common import ConversionRequest, ConversionResult, add_activity_inputs, add_coupon_inputs, date_value, empty_tables, finish_conversion, index_header, number_value, source_rows, value
from mvp.standard_schema import SHEET_COLUMNS


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
            order_lookup[order_no] = record
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
    activity_by_order: dict[str, dict[str, str]] = {}
    activity = request.activity_inputs[0] if request.activity_inputs else {}
    for path in request.source_paths.get("activity_execution", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            order_no = value(row, indexes, "订单号")
            if not order_no:
                continue
            order = order_lookup.get(order_no, {})
            activity_by_order[order_no] = {
                "活动编号": str(activity.get("活动编号", "") or ""), "活动名称": str(activity.get("活动名称", "") or ""),
                "客户编号": order.get("客户编号", ""), "客户": order.get("客户名称", value(row, indexes, "客户")),
                "所属业务员": order.get("业务员", ""), "订单号": order_no,
                "商品总金额": number_value(value(row, indexes, "商品总金额")), "优惠金额": number_value(value(row, indexes, "促销优惠金额")),
            }
    tables["标准活动核销明细"].extend(activity_by_order.values())
    for record in tables["标准订单明细"]:
        execution = activity_by_order.get(record["单据编号"])
        if execution:
            record["活动编号"] = execution["活动编号"]
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
    for order_no, order in order_lookup.items():
        tables["标准履约"].append({"单据编号": order_no, "下游订单编号": "", "履约订单状态": order.get("订单状态", ""), "出库时间": "", "完成时间": "", "结款状态": "", "退货数量": ""})
    add_activity_inputs(tables, request.activity_inputs)
    add_coupon_inputs(tables, request.coupon_inputs)
    return finish_conversion(request, tables, [f"platform=快马", f"orders={len(order_lookup)}"])
