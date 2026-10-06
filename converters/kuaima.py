"""快马 source files -> reviewed standard workbook."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from .common import ConversionRequest, ConversionResult, add_activity_inputs, add_coupon_inputs, date_value, empty_tables, finish_conversion, index_header, number_value, source_rows, value


def convert_kuaima(request: ConversionRequest) -> ConversionResult:
    tables = empty_tables()
    order_lookup: dict[str, dict[str, str]] = {}
    completed_orders: set[str] = set()
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
        file_orders: set[str] = set()
        for row in rows:
            order_no = value(row, indexes, "订单编号")
            if not order_no or order_no in completed_orders:
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
            file_orders.add(order_no)
        completed_orders.update(file_orders)
    known_products = {row["商品编号"] for row in tables["标准商品"]}
    for record in tables["标准订单明细"]:
        product_no = record["商品编号"]
        if product_no and product_no not in known_products:
            tables["标准商品"].append({
                "商品编号": product_no, "商品名称": record["商品名称"], "商品品牌": "", "商品目录": record["商品目录"],
                "商品条码": record["商品条码"], "商品规格": record["规格"], "基本单位": record["单位"], "箱规": "", "每箱基本单位数量": "",
            })
            known_products.add(product_no)
    known_customers = {row["客户编号"] for row in tables["标准客户"]}
    for record in tables["标准订单明细"]:
        _ensure_customer(tables, known_customers, record["客户编号"], record["客户名称"], record["业务员"])
    executions, unbound_files, skipped_orders = _activity_executions(request, order_lookup)
    tables["标准活动核销明细"].extend(executions.values())
    activity_numbers: dict[str, list[str]] = defaultdict(list)
    for execution in executions.values():
        activity_no = execution["活动编号"]
        if activity_no and activity_no not in activity_numbers[execution["订单号"]]:
            activity_numbers[execution["订单号"]].append(activity_no)
    for record in tables["标准订单明细"]:
        numbers = activity_numbers.get(record["单据编号"])
        if numbers:
            record["活动编号"] = "、".join(numbers)
    for path in request.source_paths.get("coupon_redemption", ()):
        header, rows = source_rows(path)
        indexes = index_header(header)
        for row in rows:
            coupon_no = value(row, indexes, "优惠券编号")
            if coupon_no:
                customer_no = value(row, indexes, "客户编号")
                customer_name = value(row, indexes, "领取人")
                salesperson = value(row, indexes, "所属业务员")
                _ensure_customer(tables, known_customers, customer_no, customer_name, salesperson)
                tables["标准优惠券核销明细"].append({
                    "优惠券编号": coupon_no, "客户编号": customer_no, "客户": customer_name,
                    "所属业务员": salesperson, "领取时间": date_value(value(row, indexes, "领取时间")),
                    "使用期限": value(row, indexes, "使用期限"), "状态": value(row, indexes, "状态"),
                    "使用时间": date_value(value(row, indexes, "使用时间")), "订单号": value(row, indexes, "使用订单号"),
                    "优惠金额": number_value(value(row, indexes, "优惠金额")),
                })
    for order_no, order in order_lookup.items():
        tables["标准履约"].append({"单据编号": order_no, "下游订单编号": "", "履约订单状态": order.get("订单状态", ""), "出库时间": "", "完成时间": "", "结款状态": "", "退货数量": ""})
    add_activity_inputs(tables, request.activity_inputs)
    add_coupon_inputs(tables, request.coupon_inputs)
    return finish_conversion(request, tables, [
        "platform=快马",
        f"orders={len(order_lookup)}",
        f"executions={len(executions)}",
        f"unbound_execution_files={len(unbound_files)}",
        f"skipped_execution_orders={skipped_orders}",
    ])


def _ensure_customer(tables: dict[str, list[dict[str, str]]], known: set[str], customer_no: str, customer_name: str, salesperson: str = "") -> None:
    if customer_no and customer_no not in known:
        tables["标准客户"].append({
            "客户编号": customer_no, "客户名称": customer_name, "客户类型": "", "客户区域": "",
            "详细地址": "", "联系电话": "", "添加时间": "", "所属业务员": salesperson,
        })
        known.add(customer_no)


def _activity_for_file(path: Path, activities: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    """Bind one execution file to an activity.

    One activity keeps every execution file. Several activities use the
    optional ``核销文件`` marker, matched against the file name.
    """
    if len(activities) <= 1:
        return activities[0] if activities else {}
    name = path.name
    matches = [activity for activity in activities if str(activity.get("核销文件", "") or "").strip() and str(activity.get("核销文件", "") or "") in name]
    return matches[0] if len(matches) == 1 else None


def _activity_executions(request: ConversionRequest, order_lookup: Mapping[str, Mapping[str, str]]) -> tuple[dict[tuple[str, str], dict[str, str]], list[str], int]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    unbound_files: list[str] = []
    skipped_orders = 0
    for path in request.source_paths.get("activity_execution", ()):
        activity = _activity_for_file(path, request.activity_inputs)
        if activity is None:
            unbound_files.append(path.name)
            continue
        header, rows = source_rows(path)
        indexes = index_header(header)
        activity_no = str(activity.get("活动编号", "") or "")
        activity_name = str(activity.get("活动名称", "") or "")
        for row in rows:
            order_no = value(row, indexes, "订单号")
            if not order_no:
                continue
            order = order_lookup.get(order_no)
            if order is None:
                skipped_orders += 1
                continue
            key = (activity_no, order_no)
            discount = _amount(value(row, indexes, "促销优惠金额"))
            product_amount = _amount(value(row, indexes, "商品总金额"))
            current = grouped.get(key)
            if current is None:
                grouped[key] = {
                    "活动编号": activity_no, "活动名称": activity_name,
                    "客户编号": order.get("客户编号", ""), "客户": order.get("客户名称", value(row, indexes, "客户")),
                    "所属业务员": order.get("业务员", ""), "订单号": order_no,
                    "商品总金额": product_amount, "优惠金额": discount,
                }
            else:
                current["商品总金额"] = float(current["商品总金额"]) + product_amount
                current["优惠金额"] = float(current["优惠金额"]) + discount
    executions = {
        key: {**row, "商品总金额": _text_number(float(row["商品总金额"])), "优惠金额": _text_number(float(row["优惠金额"]))}
        for key, row in grouped.items()
    }
    return executions, unbound_files, skipped_orders


def _amount(raw: str) -> float:
    text = number_value(raw)
    return float(text) if text else 0.0


def _text_number(number: float) -> str:
    rounded = round(number, 2)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)
