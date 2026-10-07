"""Project 羿柏 facts from the original MVP library into standard.xlsx.

`mvp/ec101_mvp.db` already has dealer 羿柏 / platform 舟谱 (CORE + 核销).
ROI reads the standard import database, so those facts are written to the
reviewed workbook contract and imported. Missing source values stay empty.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mvp.roi import box_factor
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import write_standard_workbook
from scripts.export_original_config_to_standard import activity_no, load_original, map_standard

ORIGINAL_DB = ROOT / "mvp" / "ec101_mvp.db"
OUT = ROOT / "docs" / "samples" / "zhoupu-verified-standard"
DEALER_ID = 2

BATCHES = {
    "返券": {
        "activity_id": 17,
        "calc_date": "2026-09-23",
    },
    "满赠": {
        "activity_id": 18,
        "calc_date": "2026-09-23",
    },
}


def _text(value) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _paid(pre, discount):
    if pre is None:
        return ""
    return float(pre) - float(discount or 0)


def _empty_tables() -> dict[str, list[dict[str, str]]]:
    return {sheet: [] for sheet in STANDARD_SHEETS if sheet != "导入清单"}


def _keep_activity(mapped: dict[str, list[dict[str, str]]], number: str) -> dict[str, list[dict[str, str]]]:
    tables = _empty_tables()
    for sheet in ("标准活动", "标准活动规则", "标准活动权益", "标准活动范围"):
        tables[sheet] = [row for row in mapped.get(sheet, []) if row.get("活动编号") == number]
    return tables


def export_batch(connection: sqlite3.Connection, mapped: dict[str, list[dict[str, str]]], name: str, activity_id: int) -> Path:
    connection.row_factory = sqlite3.Row
    activity = dict(connection.execute("SELECT * FROM activity WHERE activity_id=?", (activity_id,)).fetchone())
    number = activity_no(activity)
    tables = _keep_activity(mapped, number)

    executions = list(connection.execute(
        """
        SELECT oa.*, oh.order_no, oh.order_time, oh.order_status, oh.pay_method, oh.order_source,
               oh.order_type, oh.downstream_order_no, oh.customer_id,
               c.platform_customer_no, c.customer_name, c.customer_type, c.customer_region,
               c.salesperson_name, c.created_at
        FROM order_activity oa
        JOIN order_header oh ON oh.order_id=oa.order_id
        LEFT JOIN customer c ON c.customer_id=oh.customer_id
        WHERE oa.activity_id=?
        ORDER BY oa.order_activity_id
        """,
        (activity_id,),
    ))
    order_ids = [row["order_id"] for row in executions]
    if not order_ids:
        raise ValueError(f"activity {activity_id} has no 核销参与单")

    placeholders = ",".join("?" * len(order_ids))
    lines = list(connection.execute(
        f"""
        SELECT ol.*, oh.order_no, oh.order_time, oh.order_status, oh.pay_method, oh.order_source,
               oh.order_type, oh.downstream_order_no, oh.customer_id,
               c.platform_customer_no, c.customer_name, c.salesperson_name,
               p.platform_product_no, p.product_name AS catalog_name, p.brand, p.category,
               p.barcode, p.spec, p.base_unit, p.box_conversion
        FROM order_line ol
        JOIN order_header oh ON oh.order_id=ol.order_id
        LEFT JOIN customer c ON c.customer_id=oh.customer_id
        LEFT JOIN product p ON p.product_id=ol.product_id
        WHERE ol.order_id IN ({placeholders})
        ORDER BY ol.order_line_id
        """,
        order_ids,
    ))
    fulfillments = list(connection.execute(
        f"""
        SELECT f.*, oh.order_no, oh.downstream_order_no
        FROM fulfillment f
        JOIN order_header oh ON oh.order_id=f.order_id
        WHERE f.order_id IN ({placeholders})
        ORDER BY f.fulfillment_id
        """,
        order_ids,
    ))

    customers: dict[str, dict[str, str]] = {}
    products: dict[str, dict[str, str]] = {}
    for row in executions:
        customer_no = _text(row["platform_customer_no"])
        if customer_no and customer_no not in customers:
            customers[customer_no] = {
                "客户编号": customer_no,
                "客户名称": _text(row["customer_name"]),
                "客户类型": _text(row["customer_type"]),
                "客户区域": _text(row["customer_region"]),
                "详细地址": "",
                "联系电话": "",
                "添加时间": _text(row["created_at"]),
                "所属业务员": _text(row["salesperson_name"]),
            }
    for row in lines:
        product_no = _text(row["platform_product_no"])
        if not product_no:
            continue
        if product_no not in products:
            factor = box_factor(row["box_conversion"])
            products[product_no] = {
                "商品编号": product_no,
                "商品名称": _text(row["catalog_name"]),
                "商品品牌": _text(row["brand"]),
                "商品目录": _text(row["category"]),
                "商品条码": _text(row["barcode"]),
                "商品规格": _text(row["spec"]),
                "基本单位": _text(row["base_unit"]),
                "箱规": _text(row["box_conversion"]),
                "每箱基本单位数量": "" if factor is None else factor,
            }
        tables["标准订单明细"].append({
            "单据编号": _text(row["order_no"]),
            "下单时间": _text(row["order_time"]),
            "客户编号": _text(row["platform_customer_no"]),
            "客户名称": _text(row["customer_name"]),
            "商品编号": product_no,
            "商品名称": _text(row["catalog_name"]),
            "商品目录": _text(row["category"]),
            "规格": _text(row["spec"]),
            "商品条码": _text(row["barcode"]),
            "单位": _text(row["order_unit"]),
            "数量": _text(row["order_qty"]),
            "优惠前金额": _text(row["pre_discount_amount"]),
            "活动编号": number,
            "优惠券编号": "",
            "优惠金额": _text(row["discount_amount"]),
            "实付金额": _paid(row["pre_discount_amount"], row["discount_amount"]),
            "业务员": _text(row["salesperson_name"]),
            "订单来源": _text(row["order_source"]),
            "订单类型": _text(row["order_type"]),
            "订单状态": _text(row["order_status"]),
            "支付方式": _text(row["pay_method"]),
            "下游订单编号": _text(row["downstream_order_no"]),
            "单价": _text(row["unit_price"]),
            "退货数量": _text(row["return_qty"]),
        })
    for row in executions:
        tables["标准活动核销明细"].append({
            "活动编号": number,
            "活动名称": _text(activity["activity_name"]),
            "客户编号": _text(row["platform_customer_no"]),
            "客户": _text(row["customer_name"]),
            "所属业务员": _text(row["salesperson_name"]),
            "订单号": _text(row["order_no"]),
            "商品总金额": _text(row["activity_product_amount"]),
            "优惠金额": _text(row["platform_actual_benefit"] if row["platform_actual_benefit"] is not None else 0),
        })
    for row in fulfillments:
        tables["标准履约"].append({
            "单据编号": _text(row["order_no"]),
            "下游订单编号": _text(row["downstream_order_no"]),
            "履约订单状态": _text(row["order_status"]),
            "出库时间": "",
            "完成时间": _text(row["completed_at"]),
            "结款状态": "",
            "退货数量": _text(row["return_qty"]),
        })
    tables["标准客户"] = list(customers.values())
    tables["标准商品"] = list(products.values())

    # Lines without a bridged product_id have no 商品编号 — drop them, do not invent a key.
    tables["标准订单明细"] = [row for row in tables["标准订单明细"] if row["商品编号"]]

    path = OUT / name / "standard.xlsx"
    write_standard_workbook(path, tables, {
        "模板版本": "v1",
        "转换工具版本": "v1",
        "经销商名称": "羿柏",
        "平台名称": "舟谱",
        "数据开始日期": _text(activity["start_time"])[:10],
        "数据结束日期": _text(activity["end_time"])[:10],
        "生成时间": datetime.now().isoformat(timespec="seconds"),
    })
    return path


def export_all(db_path: Path = ORIGINAL_DB) -> list[Path]:
    original = load_original(db_path)
    mapped, _leftover = map_standard(original)
    connection = sqlite3.connect(db_path)
    try:
        return [export_batch(connection, mapped, name, spec["activity_id"]) for name, spec in BATCHES.items()]
    finally:
        connection.close()


def main() -> None:
    paths = export_all()
    for path in paths:
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
