"""ROI for one activity or one coupon, computed from existing standard facts.

Confirmed rules:
- orders = 核销参与单 AND 订单状态=已完成 AND 下单时间 in 上线期间
- 可口可乐 = product.brand == '可口可乐'
- 金额 = SUM(order_line.paid_amount) on those Coke lines
- 销量 = 行数量换算成瓶/罐（箱/件 × 箱规）
- 费用 = SUM(核销优惠) on the same completed participating orders
- 满赠只出金额，不算 ROI
- 券期间用使用开始/结束；活动期间用活动开始/结束
- 期间缺失则不出数，不拿导入批次期间顶替
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

COKE_BRAND = "可口可乐"
COMPLETED = "已完成"
BOX_UNITS = frozenset({"箱", "件"})
BASE_UNITS = frozenset({"瓶", "罐"})
_BOTTLE_FACTOR = re.compile(r"(\d+(?:\.\d+)?)\s*(瓶|罐)")


def _number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def box_factor(box_conversion=None, base_qty_per_box=None) -> float | None:
    """Read 箱规 as bottles/cans per box. '1箱=24瓶' is 24, not the leading 1."""
    numeric = _number(base_qty_per_box) or _number(box_conversion)
    if numeric is not None:
        return numeric
    matches = _BOTTLE_FACTOR.findall(str(box_conversion or ""))
    if matches:
        return float(matches[-1][0])
    return None


def base_qty(quantity, unit, box_conversion=None, base_qty_per_box=None) -> float | None:
    """Convert one order-line quantity to 瓶/罐. Missing factor is not invented."""
    qty = float(quantity or 0)
    unit = str(unit or "").strip()
    if unit in BASE_UNITS:
        return qty
    factor = box_factor(box_conversion, base_qty_per_box)
    if unit in BOX_UNITS and factor is not None:
        return qty * factor
    return None


def _has_period(start, end) -> bool:
    return bool(str(start or "").strip() and str(end or "").strip())


def _money(value) -> float:
    return round(float(value or 0), 2)


def _roi(paid: float, fee: float, show_ratio: bool) -> float | None:
    if not show_ratio or fee <= 0:
        return None
    return round(paid / fee, 2)


def _coke_sales(db: sqlite3.Connection, sql: str, params: tuple) -> tuple[int, float, float]:
    row = db.execute(sql, params).fetchone()
    return int(row["orders"] or 0), _money(row["paid_amount"]), round(float(row["qty_base"] or 0), 2)


COKE_SELECT = """
SELECT COUNT(DISTINCT oh.order_id) AS orders,
       COALESCE(SUM(ol.paid_amount), 0) AS paid_amount,
       COALESCE(SUM(
         CASE
           WHEN ol.unit IN ('瓶', '罐') THEN ol.quantity
           WHEN ol.unit IN ('箱', '件') THEN ol.quantity * COALESCE(
             NULLIF(CAST(p.base_qty_per_box AS REAL), 0),
             NULLIF(CAST(p.box_conversion AS REAL), 0)
           )
         END
       ), 0) AS qty_base
"""


def activity_roi(db: sqlite3.Connection, activity_id: int) -> dict:
    header = db.execute(
        """
        SELECT a.activity_id, a.activity_no, a.activity_name, a.activity_type, a.start_time, a.end_time,
               a.import_batch_id
        FROM activity a WHERE a.activity_id=?
        """,
        (activity_id,),
    ).fetchone()
    if header is None:
        raise KeyError(f"activity {activity_id}")
    start, end = header["start_time"], header["end_time"]
    is_gift = "赠" in (header["activity_type"] or "")
    if not _has_period(start, end):
        return {
            "kind": "gift" if is_gift else "money",
            "activityId": header["activity_id"],
            "name": header["activity_name"],
            "periodStart": start,
            "periodEnd": end,
            "periodMissing": True,
            "completedOrders": None,
            "cokeQtyBase": None,
            "cokePaidAmount": None,
            "feeAmount": None,
            "roi": None,
        }
    orders, paid, qty = _coke_sales(
        db,
        COKE_SELECT
        + """
        FROM activity_execution ae
        JOIN order_header oh ON oh.order_id=ae.order_id
        JOIN order_line ol ON ol.order_id=oh.order_id
        JOIN product p ON p.import_batch_id=oh.import_batch_id AND p.product_no=ol.product_no
        WHERE ae.activity_id=? AND oh.order_status=? AND p.brand=?
          AND oh.order_time>=? AND oh.order_time<=?
        """,
        (activity_id, COMPLETED, COKE_BRAND, start, end),
    )
    fee = _money(db.execute(
        """
        SELECT COALESCE(SUM(ae.discount_amount), 0)
        FROM activity_execution ae
        JOIN order_header oh ON oh.order_id=ae.order_id
        WHERE ae.activity_id=? AND oh.order_status=? AND oh.order_time>=? AND oh.order_time<=?
        """,
        (activity_id, COMPLETED, start, end),
    ).fetchone()[0])
    return {
        "kind": "gift" if is_gift else "money",
        "activityId": header["activity_id"],
        "activityNo": header["activity_no"],
        "name": header["activity_name"],
        "periodStart": start,
        "periodEnd": end,
        "periodMissing": False,
        "completedOrders": orders,
        "cokeQtyBase": qty,
        "cokePaidAmount": paid,
        "feeAmount": fee,
        "roi": _roi(paid, fee, show_ratio=not is_gift),
    }


def coupon_roi(db: sqlite3.Connection, coupon_config_id: int) -> dict:
    header = db.execute(
        """
        SELECT cc.coupon_config_id, cc.config_no, cc.coupon_name, cc.import_batch_id,
               cur.use_start_at, cur.use_end_at
        FROM coupon_config cc
        LEFT JOIN coupon_use_rule cur ON cur.coupon_config_id=cc.coupon_config_id
        WHERE cc.coupon_config_id=?
        """,
        (coupon_config_id,),
    ).fetchone()
    if header is None:
        raise KeyError(f"coupon {coupon_config_id}")
    start, end = header["use_start_at"], header["use_end_at"]
    if not _has_period(start, end):
        return {
            "kind": "coupon",
            "couponConfigId": header["coupon_config_id"],
            "configNo": header["config_no"],
            "name": header["coupon_name"],
            "periodStart": start,
            "periodEnd": end,
            "periodMissing": True,
            "completedOrders": None,
            "cokeQtyBase": None,
            "cokePaidAmount": None,
            "feeAmount": None,
            "roi": None,
        }
    orders, paid, qty = _coke_sales(
        db,
        COKE_SELECT
        + """
        FROM coupon_redemption red
        JOIN order_header oh ON oh.order_id=red.order_id
        JOIN order_line ol ON ol.order_id=oh.order_id
        JOIN product p ON p.import_batch_id=oh.import_batch_id AND p.product_no=ol.product_no
        WHERE red.import_batch_id=? AND oh.order_status=? AND p.brand=?
          AND oh.order_time>=? AND oh.order_time<=?
        """,
        (header["import_batch_id"], COMPLETED, COKE_BRAND, start, end),
    )
    fee = _money(db.execute(
        """
        SELECT COALESCE(SUM(red.discount_amount), 0)
        FROM coupon_redemption red
        JOIN order_header oh ON oh.order_id=red.order_id
        WHERE red.import_batch_id=? AND oh.order_status=? AND oh.order_time>=? AND oh.order_time<=?
        """,
        (header["import_batch_id"], COMPLETED, start, end),
    ).fetchone()[0])
    return {
        "kind": "coupon",
        "couponConfigId": header["coupon_config_id"],
        "configNo": header["config_no"],
        "name": header["coupon_name"],
        "periodStart": start,
        "periodEnd": end,
        "periodMissing": False,
        "completedOrders": orders,
        "cokeQtyBase": qty,
        "cokePaidAmount": paid,
        "feeAmount": fee,
        "roi": _roi(paid, fee, show_ratio=True),
    }


def query_roi(db_path: Path) -> list[dict]:
    """One row per current-batch activity with fee summary, plus each coupon config."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = []
        for activity_id, in connection.execute(
            """
            SELECT a.activity_id
            FROM activity a
            JOIN import_batch ib ON ib.import_batch_id=a.import_batch_id
            WHERE ib.is_current=1
              AND EXISTS (
                SELECT 1 FROM activity_execution ae WHERE ae.activity_id=a.activity_id
              )
            ORDER BY a.import_batch_id, a.activity_id
            """
        ):
            rows.append(activity_roi(connection, activity_id))
        for coupon_id, in connection.execute(
            """
            SELECT cc.coupon_config_id
            FROM coupon_config cc
            JOIN import_batch ib ON ib.import_batch_id=cc.import_batch_id
            WHERE ib.is_current=1
            ORDER BY cc.coupon_config_id
            """
        ):
            rows.append(coupon_roi(connection, coupon_id))
        return rows
    finally:
        connection.close()
