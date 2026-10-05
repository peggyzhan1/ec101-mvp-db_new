"""舟谱 SXD/XD source files -> reviewed standard workbook."""

from __future__ import annotations

from .common import ConversionRequest, ConversionResult, add_activity_inputs, add_coupon_inputs, date_value, empty_tables, finish_conversion, index_header, number_value, source_rows, value


def convert_zhoupu(request: ConversionRequest) -> ConversionResult:
    tables = empty_tables()
    for path in request.source_paths.get("customer", ()):
        header, rows = source_rows(path, header_row=4)
        indexes = index_header(header)
        for row in rows:
            customer_no = value(row, indexes, "客户唯一序号", "客户编码")
            if customer_no:
                tables["标准客户"].append({
                    "客户编号": customer_no, "客户名称": value(row, indexes, "客户名称"), "客户类型": "",
                    "客户区域": value(row, indexes, "片区"), "详细地址": value(row, indexes, "客户地址"),
                    "联系电话": value(row, indexes, "老板电话"), "添加时间": "", "所属业务员": value(row, indexes, "专属员工"),
                })
    for path in request.source_paths.get("product", ()):
        header, rows = source_rows(path, header_row=4)
        indexes = index_header(header)
        for row in rows:
            product_no = value(row, indexes, "商品唯一序号", "商品编号", "商品id")
            if product_no:
                tables["标准商品"].append({
                    "商品编号": product_no, "商品名称": value(row, indexes, "商品名称"), "商品品牌": value(row, indexes, "品牌"),
                    "商品目录": value(row, indexes, "类别"), "商品条码": value(row, indexes, "小单位条码", "条形码"),
                    "商品规格": value(row, indexes, "规格"), "基本单位": "", "箱规": value(row, indexes, "单位换算"),
                    "每箱基本单位数量": number_value(value(row, indexes, "大单位换算")),
                })
    orders: dict[str, dict[str, str]] = {}
    for path in request.source_paths.get("order_detail", ()):
        header, rows = source_rows(path, header_row=4)
        indexes = index_header(header)
        for row in rows:
            order_no = value(row, indexes, "订单编号")
            if not order_no:
                continue
            record = {
                "单据编号": order_no, "下单时间": date_value(value(row, indexes, "下单时间")),
                "客户编号": value(row, indexes, "客户编码"), "客户名称": value(row, indexes, "客户名称"),
                "商品编号": value(row, indexes, "商品编号"), "商品名称": value(row, indexes, "商品名称"),
                "商品目录": value(row, indexes, "类目"), "规格": value(row, indexes, "规格"),
                "商品条码": value(row, indexes, "商品条码"), "单位": value(row, indexes, "单位名称", "单位名称（大）"),
                "数量": number_value(value(row, indexes, "实际数量", "订单数量（大）", "订单数量")),
                "优惠前金额": number_value(value(row, indexes, "优惠前金额")), "活动编号": "", "优惠券编号": "",
                "优惠金额": "", "实付金额": number_value(value(row, indexes, "实际金额")), "业务员": "",
                "订单来源": "", "订单类型": "", "订单状态": value(row, indexes, "订单状态"),
                "支付方式": "", "下游订单编号": value(row, indexes, "下游订单编号"),
                "单价": number_value(value(row, indexes, "实际单价")), "退货数量": "",
            }
            tables["标准订单明细"].append(record)
            orders[order_no] = record
    for path in request.source_paths.get("fulfillment", ()):
        header, rows = source_rows(path, header_row=4)
        indexes = index_header(header)
        for row in rows:
            xd_no = value(row, indexes, "单据")
            if not xd_no:
                continue
            tables["标准履约"].append({
                "单据编号": value(row, indexes, "综合订单号"), "下游订单编号": xd_no,
                "履约订单状态": value(row, indexes, "订单状态"), "出库时间": date_value(value(row, indexes, "出(入)库时间")),
                "完成时间": date_value(value(row, indexes, "签收时间")), "结款状态": value(row, indexes, "结款状态"),
                "退货数量": number_value(value(row, indexes, "退货结算数量")),
            })
    add_activity_inputs(tables, request.activity_inputs)
    add_coupon_inputs(tables, request.coupon_inputs)
    return finish_conversion(request, tables, ["platform=舟谱", f"orders={len(orders)}"])
