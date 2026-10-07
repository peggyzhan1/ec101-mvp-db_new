"""舟谱-羿柏试点全量快照 → 标准工作簿。

业务口径与 mvp/scripts/ingest_zhoupu.py、ingest_result_zhoupu.py 已核验的接入一致：
客户复合键、履约状态权威、XD-only 建单、券台账双单号不在转换阶段归因。
满赠应赠/实赠与 T-2 由 result 层计算。
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from converters.common import (
    ConversionRequest,
    ConversionResult,
    add_activity_inputs,
    add_coupon_inputs,
    build_sources_archive,
    date_value,
    empty_tables,
    source_rows,
)
from mvp.scripts.readers import to_num
from mvp.standard_workbook import write_standard_workbook_fast

STATUS_RANK = {"待审核": 0, "待出库": 1, "待入库": 2, "待签收": 3, "已完成": 4}
QTY_COLUMNS = ["下单数量", "下单数量（小）", "下单数量(小)", "下单数量（中）", "下单数量（大）"]
GIFT_PRODUCT_NAME = "(赠品)雪碧抱枕"
UNRESOLVED_PREFIX = "UNRESOLVED:"
UNMATCHED_PREFIX = "UNMATCHED:"

SXD_FILES = (
    "满减/舟谱-羿柏-订单明细 0826-0827.xlsx",
    "满减/舟谱-羿柏-订单明细 0828-0830.xlsx",
    "满减/舟谱-羿柏-订单明细 0831-0902.xlsx",
    "满减/舟谱-羿柏-订单明细 0903-0905.xlsx",
    "满减/舟谱-羿柏-订单明细 0906-0908.xlsx",
    "满赠/满赠订单明细20260819-20260821.xlsx",
    "满赠/满赠订单明细20260822-20260823.xlsx",
    "满赠/满赠订单明细20260824-20260826.xlsx",
)
XD_FILES = (
    "满减/舟谱-羿柏-订单明细-XD-20260826-20260908.xlsx",
    "满赠/满赠XD20260819-20260826.xlsx",
)
COUPON_FILE = "满减/舟谱-羿柏-活动明细-20260826-20260908.xls"

GIFT_ACTIVITY: dict[str, Any] = {
    "活动编号": "ZP-MZ-001",
    "活动名称": "雪碧系列满100元送抱枕",
    "活动类型": "满赠",
    "促销方式": "满一定金额立赠",
    "开始时间": "2026-08-19 00:00:00",
    "结束时间": "2026-08-26 23:59:59",
    "是否允许叠加活动": "",
    "是否允许叠加优惠券": "",
    "活动状态": "已结束",
    "规则": [{
        "活动编号": "ZP-MZ-001", "规则编号": "R1", "门槛类型": "金额", "门槛值": "100", "立减金额": "0", "是否免邮": "",
    }],
    "权益": [{
        "活动编号": "ZP-MZ-001", "规则编号": "R1", "权益编号": "B1", "权益类型": "赠品",
        "赠品商品编号": "", "赠品商品名称": GIFT_PRODUCT_NAME, "赠品数量": "1", "赠品单位": "",
    }],
    "范围": [
        {"活动编号": "ZP-MZ-001", "范围编号": "S1", "范围类别": "商品", "范围维度": "商品名称前缀", "范围值": "雪碧"},
        {"活动编号": "ZP-MZ-001", "范围编号": "S2", "范围类别": "限购", "范围维度": "每客户次数", "范围值": "1"},
    ],
}

COUPON_CONFIG: dict[str, Any] = {
    "优惠券配置编号": "ZP-FQ-CFG",
    "优惠券名称": "可口可乐产品288返15元券",
    "券类型": "满返",
    "配置状态": "已结束",
    "发放方式": "下单返券",
    "发放开始时间": "2026-08-26 00:00:00",
    "发放结束时间": "2026-09-08 23:59:59",
    "自动发放时间": "",
    "每次发放数量": "1",
    "每客户领取上限": "",
    "每日领取上限": "",
    "规则状态": "已结束",
    "有效期类型": "固定期间",
    "使用开始时间": "2026-08-26 00:00:00",
    "使用结束时间": "2026-09-08 23:59:59",
    "领取后有效天数": "",
    "每张券最多使用次数": "1",
    "范围": [],
}


def pilot_source_paths(base: Path) -> dict[str, list[Path]]:
    return {
        "customer": [base / "客户档案-20260914.xlsx"],
        "product": [base / "商品档案-20260914.xlsx"],
        "order_detail": [base / relative for relative in SXD_FILES],
        "fulfillment": [base / relative for relative in XD_FILES],
        "coupon_redemption": [base / COUPON_FILE],
    }


def norm_id(value: object) -> str:
    text = "" if value is None else str(value).strip()
    matched = re.match(r"^(\d+)\.0+$", text)
    return matched.group(1) if matched else text


def agg_status(statuses: Sequence[str]) -> str:
    present = [status for status in statuses if status]
    if not present:
        return ""
    if all(status == "已完成" for status in present):
        return "已完成"
    unknown = [status for status in present if status not in STATUS_RANK]
    if unknown:
        return unknown[0]
    return min(present, key=lambda status: STATUS_RANK[status])


def first_index(header: Sequence[str]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, name in enumerate(header):
        key = str(name).strip()
        if key and key not in indexes:
            indexes[key] = index
    return indexes


def cell(row: Sequence[Any], indexes: Mapping[str, int], name: str) -> str:
    index = indexes.get(name)
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def date19(raw: str) -> str:
    text = date_value(raw)
    if len(text) == 10:
        return text + " 00:00:00"
    return text


def text_num(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(float(value) + 0.0, 2)
    if float(rounded).is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}"


def parse_per_box(*texts: object) -> float | None:
    for raw in texts:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        number = to_num(text)
        if number is not None and number > 0:
            return float(number)
        matched = re.search(r"(\d+(?:\.\d+)?)\s*[*×xX]\s*(\d+(?:\.\d+)?)", text)
        if matched:
            return float(matched.group(2))
        matched = re.search(r"(\d+(?:\.\d+)?)", text)
        if matched and float(matched.group(1)) > 0:
            return float(matched.group(1))
    return None


def _load_customers(paths: Sequence[Path]) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    by_composite: dict[str, dict[str, str]] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        header, rows = source_rows(path, header_row=4)
        indexes = first_index(header)
        for row in rows:
            name = cell(row, indexes, "客户名称")
            mnemonic = cell(row, indexes, "助记码") or cell(row, indexes, "客户助记码")
            composite = f"{name}|{mnemonic}"
            if composite in by_composite:
                continue
            by_composite[composite] = {
                "客户编号": composite,
                "客户名称": name,
                "客户类型": "",
                "客户区域": cell(row, indexes, "片区"),
                "详细地址": cell(row, indexes, "客户地址"),
                "联系电话": cell(row, indexes, "老板电话"),
                "添加时间": "",
                "所属业务员": cell(row, indexes, "专属员工"),
            }
            if name:
                by_name[name].append(composite)
    return by_composite, by_name


def _load_products(paths: Sequence[Path]) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    by_no: dict[str, dict[str, str]] = {}
    by_barcode: dict[str, str] = {}
    for path in paths:
        header, rows = source_rows(path, header_row=4)
        indexes = first_index(header)
        for row in rows:
            product_no = norm_id(cell(row, indexes, "商品唯一序号"))
            if not product_no or product_no in by_no:
                continue
            barcode = norm_id(cell(row, indexes, "小单位条码"))
            per_box = parse_per_box(cell(row, indexes, "大单位换算"), cell(row, indexes, "单位换算"))
            by_no[product_no] = {
                "商品编号": product_no,
                "商品名称": cell(row, indexes, "商品名称"),
                "商品品牌": cell(row, indexes, "品牌"),
                "商品目录": cell(row, indexes, "类别"),
                "商品条码": barcode,
                "商品规格": "",
                "基本单位": "",
                "箱规": cell(row, indexes, "单位换算"),
                "每箱基本单位数量": text_num(per_box),
            }
            if barcode and barcode not in by_barcode:
                by_barcode[barcode] = product_no
    return by_no, by_barcode


def _xd_indexes(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    orders: dict[str, dict[str, Any]] = {}
    for path in paths:
        header, rows = source_rows(path, header_row=4)
        indexes = first_index(header)
        has_return = "退货结算数量" in indexes
        for row in rows:
            document = cell(row, indexes, "单据")
            if not document:
                continue
            current = orders.get(document)
            if current is None:
                current = orders[document] = {
                    "mnem": "", "cname": "", "settle": "", "statuses": [], "signs": [], "outs": [],
                    "rets": [], "has_return": has_return, "by_barcode": {}, "by_name": {},
                }
            for field, column in (("mnem", "客户助记码"), ("cname", "客户名称"), ("settle", "结款状态")):
                if not current[field]:
                    value = cell(row, indexes, column)
                    if value:
                        current[field] = value
            current["statuses"].append(cell(row, indexes, "订单状态"))
            signed = date19(cell(row, indexes, "签收时间"))
            outbound = date19(cell(row, indexes, "出(入)库时间"))
            if signed:
                current["signs"].append(signed)
            if outbound:
                current["outs"].append(outbound)
            if has_return:
                returned = to_num(cell(row, indexes, "退货结算数量"))
                if returned is not None:
                    current["rets"].append(returned)
            product_no = norm_id(cell(row, indexes, "商品id"))
            barcode = norm_id(cell(row, indexes, "条形码"))
            name = cell(row, indexes, "商品名称")
            if product_no and barcode:
                current["by_barcode"].setdefault((document, barcode), product_no)
            if product_no and name:
                current["by_name"].setdefault((document, name), product_no)
    for current in orders.values():
        current["status"] = agg_status(current["statuses"])
        current["completed_at"] = max(current["signs"]) if current["signs"] else (max(current["outs"]) if current["outs"] else "")
        current["return_qty"] = round(sum(current["rets"]), 2) if current["has_return"] else None
    return orders


def _match_customer(order_name: str, xd: Mapping[str, Any] | None, customers: Mapping[str, dict[str, str]], by_name: Mapping[str, Sequence[str]]) -> str:
    if xd:
        for composite in (f"{xd['cname']}|{xd['mnem']}", f"{order_name}|{xd['mnem']}"):
            if composite in customers:
                return composite
    for name in (order_name, xd["cname"] if xd else ""):
        matches = by_name.get(name or "", ())
        if len(matches) == 1:
            return matches[0]
    return ""


def _match_product(downstream: str, barcode: str, name: str, xd_orders: Mapping[str, Mapping[str, Any]], products: Mapping[str, dict[str, str]], by_barcode: Mapping[str, str]) -> str:
    xd = xd_orders.get(downstream) if downstream else None
    if xd:
        product_no = xd["by_barcode"].get((downstream, barcode)) if barcode else None
        if product_no is None and name:
            product_no = xd["by_name"].get((downstream, name))
        if product_no and product_no in products:
            return product_no
    if barcode and barcode in by_barcode:
        return by_barcode[barcode]
    return ""


def _blank_customer(customer_no: str, name: str) -> dict[str, str]:
    return {"客户编号": customer_no, "客户名称": name, "客户类型": "", "客户区域": "", "详细地址": "", "联系电话": "", "添加时间": "", "所属业务员": ""}


def _blank_product(product_no: str, name: str, barcode: str) -> dict[str, str]:
    return {
        "商品编号": product_no, "商品名称": name, "商品品牌": "", "商品目录": "", "商品条码": barcode,
        "商品规格": "", "基本单位": "", "箱规": "", "每箱基本单位数量": "",
    }


def _order_line(header: Mapping[str, str], line: Mapping[str, Any]) -> dict[str, str]:
    return {
        "单据编号": header["单据编号"], "下单时间": header["下单时间"], "客户编号": header["客户编号"], "客户名称": header["客户名称"],
        "商品编号": line["product_no"], "商品名称": line["product_name"], "商品目录": line.get("category", ""), "规格": line.get("spec", ""),
        "商品条码": line.get("barcode", ""), "单位": line.get("unit", ""), "数量": text_num(line["qty"]),
        "优惠前金额": text_num(line["pre"]), "活动编号": "", "优惠券编号": "", "优惠金额": text_num(line["discount"]),
        "实付金额": text_num(line["paid"]), "业务员": "", "订单来源": header["订单来源"], "订单类型": "",
        "订单状态": header["订单状态"], "支付方式": "", "下游订单编号": header["下游订单编号"], "单价": text_num(line.get("price")),
        "退货数量": "",
    }


def _ensure_party(tables: dict[str, list[dict[str, str]]], seen: set[str], sheet: str, key: str, row: dict[str, str]) -> None:
    if key in seen:
        return
    tables[sheet].append(row)
    seen.add(key)


def _convert_sxd(tables, customers, by_name, products, by_barcode, xd_orders, paths: Sequence[Path], seen_customers: set[str], seen_products: set[str]) -> set[str]:
    order_first: dict[str, tuple[str, dict[str, str]]] = {}
    order_lines: dict[str, list[dict[str, str]]] = defaultdict(list)
    referenced: set[str] = set()
    for path in paths:
        header, rows = source_rows(path, header_row=4)
        indexes = first_index(header)
        file_name = path.name
        for row in rows:
            order_no = cell(row, indexes, "订单编号")
            if not order_no.startswith("SXD"):
                continue
            mapped = {name: cell(row, indexes, name) for name in indexes}
            if order_no not in order_first:
                order_first[order_no] = (file_name, mapped)
                order_lines[order_no].append(mapped)
            elif order_first[order_no][0] == file_name:
                order_lines[order_no].append(mapped)
    for order_no, (_, header_row) in order_first.items():
        downstream = header_row.get("下游订单编号", "")
        if downstream:
            referenced.add(downstream)
        xd = xd_orders.get(downstream) if downstream else None
        status = xd["status"] if xd else header_row.get("订单状态", "")
        if not status:
            status = "未知"
        customer_no = _match_customer(header_row.get("客户名称", ""), xd, customers, by_name)
        customer_name = header_row.get("客户名称", "")
        if not customer_no:
            customer_no = f"{UNRESOLVED_PREFIX}{order_no}"
            _ensure_party(tables, seen_customers, "标准客户", customer_no, _blank_customer(customer_no, customer_name))
        elif customer_no in customers:
            customer_name = customers[customer_no]["客户名称"] or customer_name
        order_header = {
            "单据编号": order_no,
            "下单时间": date19(header_row.get("下单时间", "")) or "1900-01-01 00:00:00",
            "客户编号": customer_no,
            "客户名称": customer_name,
            "订单来源": "",
            "订单状态": status,
            "下游订单编号": downstream,
        }
        aggregated: dict[str, dict[str, Any]] = {}
        for sequence, line in enumerate(order_lines[order_no]):
            barcode = norm_id(line.get("商品条码", ""))
            name = line.get("商品名称", "")
            product_no = _match_product(downstream, barcode, name, xd_orders, products, by_barcode)
            if product_no:
                product_name = products[product_no]["商品名称"] or name
                product_barcode = products[product_no]["商品条码"] or barcode
            else:
                product_no = f"{UNMATCHED_PREFIX}{barcode or name or line.get('商品编号') or sequence}"
                product_name = name
                product_barcode = barcode
                _ensure_party(tables, seen_products, "标准商品", product_no, _blank_product(product_no, product_name, product_barcode))
            quantity = to_num(line.get("实际数量") or line.get("订单数量（大）") or line.get("订单数量"))
            pre = to_num(line.get("优惠前金额"))
            paid = to_num(line.get("实际金额"))
            price = to_num(line.get("实际单价"))
            discount = (pre - paid) if pre is not None and paid is not None else None
            current = aggregated.get(product_no)
            if current is None:
                aggregated[product_no] = {
                    "product_no": product_no, "product_name": product_name, "barcode": product_barcode,
                    "category": line.get("类目", ""), "unit": line.get("单位名称") or line.get("单位名称（大）") or "",
                    "qty": quantity or 0.0, "pre": pre or 0.0, "paid": paid or 0.0, "discount": discount or 0.0, "price": price,
                }
            else:
                current["qty"] += quantity or 0.0
                current["pre"] += pre or 0.0
                current["paid"] += paid or 0.0
                current["discount"] += discount or 0.0
        for line in aggregated.values():
            tables["标准订单明细"].append(_order_line(order_header, line))
        if xd:
            tables["标准履约"].append({
                "单据编号": order_no, "下游订单编号": downstream, "履约订单状态": xd["status"] or "未知",
                "出库时间": max(xd["outs"]) if xd["outs"] else "", "完成时间": xd["completed_at"],
                "结款状态": xd["settle"], "退货数量": text_num(xd["return_qty"]),
            })
    return referenced


def _quantity_of(row: Sequence[Any], indexes: Mapping[str, int]) -> float | None:
    for name in QTY_COLUMNS:
        number = to_num(cell(row, indexes, name))
        if number is not None:
            return number
    return None


def _convert_xd_only(tables, customers, products, xd_orders, paths: Sequence[Path], referenced: set[str], seen_customers: set[str], seen_products: set[str]) -> int:
    seen_documents: set[str] = set()
    created = 0
    for path in paths:
        header, rows = source_rows(path, header_row=4)
        indexes = first_index(header)
        grouped: dict[str, list[Sequence[Any]]] = defaultdict(list)
        for row in rows:
            document = cell(row, indexes, "单据")
            if document:
                grouped[document].append(row)
        for document, document_rows in grouped.items():
            if document in seen_documents or document in referenced or document.startswith("TD") or not document.startswith("XD"):
                seen_documents.add(document)
                continue
            seen_documents.add(document)
            name = mnemonic = document_time = ""
            statuses: list[str] = []
            signs: list[str] = []
            outs: list[str] = []
            for row in document_rows:
                name = name or cell(row, indexes, "客户名称")
                mnemonic = mnemonic or cell(row, indexes, "客户助记码")
                document_time = document_time or date19(cell(row, indexes, "单据时间"))
                statuses.append(cell(row, indexes, "订单状态"))
                signed = date19(cell(row, indexes, "签收时间"))
                outbound = date19(cell(row, indexes, "出(入)库时间"))
                if signed:
                    signs.append(signed)
                if outbound:
                    outs.append(outbound)
            if name == "测试":
                continue
            status = agg_status(statuses) or "未知"
            completed_at = max(signs) if signs else (max(outs) if outs else "")
            composite = f"{name}|{mnemonic}"
            if composite in customers:
                customer_no = composite
                customer_name = customers[composite]["客户名称"] or name
            else:
                customer_no = f"{UNRESOLVED_PREFIX}{document}"
                customer_name = name
                _ensure_party(tables, seen_customers, "标准客户", customer_no, _blank_customer(customer_no, customer_name))
            xd = xd_orders.get(document)
            order_header = {
                "单据编号": document,
                "下单时间": document_time or completed_at or "1900-01-01 00:00:00",
                "客户编号": customer_no,
                "客户名称": customer_name,
                "订单来源": "XD履约(无SXD)",
                "订单状态": status,
                "下游订单编号": "",
            }
            aggregated: dict[str, dict[str, Any]] = {}
            for row in document_rows:
                product_no = norm_id(cell(row, indexes, "商品id"))
                raw_name = cell(row, indexes, "商品名称")
                if product_no and product_no in products:
                    product_name = products[product_no]["商品名称"] or raw_name
                    barcode = products[product_no]["商品条码"]
                else:
                    product_no = f"{UNMATCHED_PREFIX}{raw_name or product_no or 'x'}"
                    product_name = raw_name
                    barcode = norm_id(cell(row, indexes, "条形码"))
                    _ensure_party(tables, seen_products, "标准商品", product_no, _blank_product(product_no, product_name, barcode))
                amount = to_num(cell(row, indexes, "下单金额")) or 0.0
                quantity = _quantity_of(row, indexes) or 0.0
                current = aggregated.get(product_no)
                if current is None:
                    aggregated[product_no] = {
                        "product_no": product_no, "product_name": product_name, "barcode": barcode, "spec": cell(row, indexes, "规格"),
                        "qty": quantity, "pre": amount, "paid": amount, "discount": 0.0, "price": None,
                    }
                else:
                    current["qty"] += quantity
                    current["pre"] += amount
                    current["paid"] += amount
            for line in aggregated.values():
                tables["标准订单明细"].append(_order_line(order_header, line))
            tables["标准履约"].append({
                "单据编号": document, "下游订单编号": "", "履约订单状态": status,
                "出库时间": max(outs) if outs else "", "完成时间": completed_at,
                "结款状态": (xd or {}).get("settle", ""), "退货数量": "",
            })
            created += 1
    return created


def _convert_coupons(tables, customers_by_name: Mapping[str, Sequence[str]], paths: Sequence[Path]) -> tuple[int, int]:
    order_nos = {row["单据编号"] for row in tables["标准订单明细"]}
    loaded = used = 0
    for path in paths:
        header, rows = source_rows(path, header_row=3)
        indexes = first_index(header)
        for index, row in enumerate(rows):
            name = cell(row, indexes, "券名")
            if not name:
                continue
            customer_name = cell(row, indexes, "领取客户")
            matches = customers_by_name.get(customer_name, ())
            customer_no = matches[0] if len(matches) == 1 else customer_name
            used_count = to_num(cell(row, indexes, "已使用张数")) or 0
            is_used = used_count > 0
            linked = cell(row, indexes, "关联单据编号")
            face = re.search(r"返(\d+(?:\.\d+)?)元?", name)
            amount = face.group(1) if face and is_used else ""
            order_no = linked if linked and "," not in linked and linked in order_nos else ""
            period = "" if order_no or not linked else f"关联单据:{linked}"
            tables["标准优惠券核销明细"].append({
                "优惠券编号": f"ZP-FQ-{index:04d}", "客户编号": customer_no or customer_name or "未知客户", "客户": customer_name,
                "所属业务员": "", "领取时间": "", "使用期限": period, "状态": "已使用" if is_used else "已领取",
                "使用时间": "", "订单号": order_no, "优惠金额": amount,
            })
            loaded += 1
            used += int(is_used)
    return loaded, used


def convert_zhoupu_snapshot(request: ConversionRequest) -> ConversionResult:
    tables = empty_tables()
    customers, by_name = _load_customers(request.source_paths.get("customer", ()))
    products, by_barcode = _load_products(request.source_paths.get("product", ()))
    tables["标准客户"].extend(customers.values())
    tables["标准商品"].extend(products.values())
    seen_customers = set(customers)
    seen_products = set(products)
    xd_orders = _xd_indexes(request.source_paths.get("fulfillment", ()))
    referenced = _convert_sxd(
        tables, customers, by_name, products, by_barcode, xd_orders,
        request.source_paths.get("order_detail", ()), seen_customers, seen_products,
    )
    xd_only = _convert_xd_only(
        tables, customers, products, xd_orders, request.source_paths.get("fulfillment", ()),
        referenced, seen_customers, seen_products,
    )
    coupons, used_coupons = _convert_coupons(tables, by_name, request.source_paths.get("coupon_redemption", ()))
    add_activity_inputs(tables, request.activity_inputs)
    add_coupon_inputs(tables, request.coupon_inputs)
    request.output_dir.mkdir(parents=True, exist_ok=True)
    source_files = [path for paths in request.source_paths.values() for path in paths]
    archive_path = request.output_dir / "sources.zip"
    archive_hash = build_sources_archive(source_files, archive_path)
    manifest = {
        "模板版本": "v1", "转换工具版本": "zhoupu-snapshot-v1", "经销商名称": request.dealer_name,
        "平台名称": request.platform, "数据开始日期": "2026-08-19", "数据结束日期": "2026-09-08",
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    workbook_path = request.output_dir / "standard.xlsx"
    write_standard_workbook_fast(workbook_path, tables, manifest)
    order_nos = {row["单据编号"] for row in tables["标准订单明细"]}
    report_lines = [
        "platform=舟谱",
        f"customers={len(customers)}",
        f"products={len(products)}",
        f"orders={len(order_nos)}",
        f"xd_only={xd_only}",
        f"order_lines={len(tables['标准订单明细'])}",
        f"fulfillments={len(tables['标准履约'])}",
        f"coupons={coupons}",
        f"used_coupons={used_coupons}",
        f"synthetic_customers={len(seen_customers) - len(customers)}",
        f"synthetic_products={len(seen_products) - len(products)}",
        f"sources_sha256={archive_hash}",
    ]
    report_path = request.output_dir / "conversion_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return ConversionResult(workbook_path, archive_path, report_path, {sheet: len(rows) for sheet, rows in tables.items()})
