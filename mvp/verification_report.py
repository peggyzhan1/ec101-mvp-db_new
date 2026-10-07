"""Fill the reviewed fee-verification workbook from one activity or one coupon × one calculation run.

Business download has three sheets: 活动核验结论, 参与订单明细, 订单商品行（附录）.
字段说明 stays in the review template only.
"""

from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from scripts.build_activity_verification_template import (
    BODY,
    HEADER,
    LABEL,
    LINE_COLUMNS,
    NOTE,
    ORDER_COLUMNS,
    TEAL,
    THIN,
    TITLE,
    _style_header,
    _write_row,
)


ORDER_NAMES = [col[0] for col in ORDER_COLUMNS]
LINE_NAMES = [col[0] for col in LINE_COLUMNS]
YES_COL = ORDER_NAMES.index("是否可释放") + 1


def _blank(value):
    return "" if value is None else value


def _money(value):
    if value in (None, ""):
        return ""
    return round(float(value), 2)


def _write_cover(ws, title: str, note: str, summary: list[tuple[str, object]]) -> None:
    ws["A1"] = title
    ws["A1"].font = TITLE
    ws.merge_cells("A1:C1")
    ws["A2"] = note
    ws["A2"].font = NOTE
    ws.merge_cells("A2:C2")
    ws["A4"] = "项目"
    ws["B4"] = "值"
    for cell in (ws["A4"], ws["B4"]):
        cell.font = HEADER
        cell.fill = TEAL
        cell.border = THIN
    for index, (label, value) in enumerate(summary, start=5):
        ws.cell(index, 1, label).font = LABEL
        ws.cell(index, 1).border = THIN
        ws.cell(index, 2, _blank(value)).font = BODY
        ws.cell(index, 2).border = THIN
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 62
    ws.column_dimensions["C"].width = 18


def _write_orders(ws, note: str, rows: list[list[object]]) -> None:
    ws["A1"] = note
    ws["A1"].font = NOTE
    ws.merge_cells("A1:Y1")
    _style_header(ws, 2, ORDER_NAMES, set())
    for offset, row in enumerate(rows):
        _write_row(ws, 3 + offset, row, (), YES_COL)
        ws.row_dimensions[3 + offset].height = 32
    widths = [6, 22, 8, 22, 16, 10, 12, 20, 24, 20, 26, 16, 20, 10, 10, 10, 10, 14, 16, 14, 14, 10, 10, 22, 12, 10, 12]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _write_lines(ws, rows: list[list[object]]) -> None:
    ws["A1"] = "附录：参与订单的商品行，便于抽查。行优惠金额不是本报告费用，不要加总当核销。"
    ws["A1"].font = NOTE
    ws.merge_cells("A1:J1")
    _style_header(ws, 2, LINE_NAMES, set())
    for offset, row in enumerate(rows):
        _write_row(ws, 3 + offset, row)
    for index, width in enumerate([24, 18, 32, 8, 8, 8, 10, 12, 12, 12], start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _order_lines(db: sqlite3.Connection, order_ids: list[int]) -> list[list[object]]:
    if not order_ids:
        return []
    placeholders = ",".join("?" for _ in order_ids)
    rows = db.execute(
        f"""
        SELECT oh.order_no, ol.product_no, ol.product_name, ol.spec, ol.quantity, ol.unit,
               ol.unit_price, ol.pre_discount_amount, ol.discount_amount, ol.paid_amount
        FROM order_line ol JOIN order_header oh ON oh.order_id=ol.order_id
        WHERE ol.order_id IN ({placeholders})
        ORDER BY oh.order_time, oh.order_no, ol.order_line_id
        """,
        order_ids,
    ).fetchall()
    return [[row[0], row[1], row[2], row[3], row[4], row[5], _money(row[6]), _money(row[7]), _money(row[8]), _money(row[9])] for row in rows]


def _save(workbook: Workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_activity_report(db_path: Path, activity_id: int, calc_batch_id: int) -> tuple[bytes, str]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        header = connection.execute(
            """
            SELECT a.activity_id, a.activity_no, a.activity_name, a.activity_type,
                   ib.dealer_name, ib.platform_name, ib.coverage_start, ib.coverage_end,
                   cr.calculation_run_id, cr.calc_date, cr.release_cutoff, cr.import_batch_id,
                   s.actual_discount_total, s.participating_orders, s.released_orders,
                   s.released_amount, s.pending_orders, s.pending_amount
            FROM activity_fee_summary s
            JOIN activity a ON a.activity_id=s.activity_id
            JOIN calculation_run cr ON cr.calculation_run_id=s.calculation_run_id
            JOIN import_batch ib ON ib.import_batch_id=cr.import_batch_id
            WHERE s.activity_id=? AND s.calculation_run_id=?
            """,
            (activity_id, calc_batch_id),
        ).fetchone()
        if header is None:
            raise KeyError(f"activity {activity_id} run {calc_batch_id}")
        orders = list(connection.execute(
            """
            SELECT oh.order_id, oh.order_no, oh.order_time, oh.customer_no, oh.customer_name, oh.salesperson,
                   oh.order_status, oh.order_source, oh.order_type, oh.payment_method,
                   ae.product_amount, ae.discount_amount AS activity_benefit,
                   (SELECT SUM(ol.discount_amount) FROM order_line ol WHERE ol.order_id=oh.order_id) AS order_discount,
                   (SELECT SUM(cr2.discount_amount) FROM coupon_redemption cr2 WHERE cr2.order_id=oh.order_id) AS coupon_benefit,
                   rc.is_candidate, rc.reason,
                   ec.theoretical_activity_benefit, ec.consistency, ec.gift_qty_actual
            FROM activity_execution ae
            JOIN order_header oh ON oh.order_id=ae.order_id
            JOIN release_candidate rc ON rc.order_id=oh.order_id AND rc.calculation_run_id=?
            JOIN entitlement_check ec ON ec.order_id=oh.order_id AND ec.calculation_run_id=?
            WHERE ae.activity_id=?
            ORDER BY oh.order_time, oh.order_no
            """,
            (calc_batch_id, calc_batch_id, activity_id),
        ))
        theoretical = sum(float(row["theoretical_activity_benefit"] or 0) for row in orders)
        consistent = sum(1 for row in orders if row["consistency"] == "一致")
        is_gift = "赠" in (header["activity_type"] or "")
        workbook = Workbook()
        cover = workbook.active
        cover.title = "活动核验结论"
        _write_cover(cover, "EC101 活动费用核验报告", "一份报告 = 一个活动 × 一次核算。计费只认本活动核销；理论只核对。", [
            ("经销商名称", header["dealer_name"]),
            ("平台名称", header["platform_name"]),
            ("活动编号", header["activity_no"]),
            ("活动名称", header["activity_name"]),
            ("活动类型", header["activity_type"]),
            ("数据期间", f"{header['coverage_start'] or ''} 至 {header['coverage_end'] or ''}"),
            ("核算日", header["calc_date"]),
            ("释放截止时刻", header["release_cutoff"]),
            ("导入批次", header["import_batch_id"]),
            ("核算批次", header["calculation_run_id"]),
            ("参与订单数", header["participating_orders"]),
            ("可释放订单数", header["released_orders"]),
            ("待释放订单数", header["pending_orders"]),
            ("活动优惠合计（核销）", _money(header["actual_discount_total"])),
            ("可释放金额", "" if is_gift else _money(header["released_amount"])),
            ("待释放金额", "" if is_gift else _money(header["pending_amount"])),
            ("理论权益合计", _money(theoretical)),
            ("一致订单数", f"{consistent} / {len(orders)}"),
            ("计费口径", "只按本活动核销明细的优惠金额；不按订单行优惠，不用规则替换费用"),
            ("释放口径", "订单状态=已完成，且下单时间早于释放截止时刻"),
        ])
        order_rows = []
        for index, row in enumerate(orders, start=1):
            activity_fee = _money(row["activity_benefit"])
            theoretical_fee = _money(row["theoretical_activity_benefit"])
            difference = ""
            if activity_fee != "" and theoretical_fee != "":
                difference = round(float(activity_fee) - float(theoretical_fee), 2)
            order_rows.append([
                index, header["dealer_name"], header["platform_name"], header["activity_no"], header["activity_name"],
                header["activity_type"], header["calc_date"], header["release_cutoff"], row["order_no"], row["order_time"],
                row["customer_no"], row["customer_name"], row["salesperson"] or "", row["order_status"],
                row["order_source"] or "", row["order_type"] or "", row["payment_method"] or "",
                _money(row["product_amount"]), _money(row["order_discount"]), activity_fee,
                _money(row["coupon_benefit"]) if row["coupon_benefit"] else "",
                row["gift_qty_actual"] if is_gift else "",
                "是" if row["is_candidate"] else "否", row["reason"],
                theoretical_fee, row["consistency"] or "", difference,
            ])
        sheet = workbook.create_sheet("参与订单明细")
        _write_orders(sheet, "一行一张参加了这个活动的订单。订单优惠只备查；关联券才填券优惠。", order_rows)
        _write_lines(workbook.create_sheet("订单商品行（附录）"), _order_lines(connection, [row["order_id"] for row in orders]))
        filename = f"核验报告-{header['activity_name']}-{header['calc_date']}.xlsx"
        return _save(workbook), filename
    finally:
        connection.close()


def build_coupon_report(db_path: Path, coupon_config_id: int, calc_batch_id: int) -> tuple[bytes, str]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        header = connection.execute(
            """
            SELECT cc.coupon_config_id, cc.config_no, cc.coupon_name, cc.coupon_type, cc.config_status,
                   ib.dealer_name, ib.platform_name, ib.coverage_start, ib.coverage_end, ib.import_batch_id,
                   cr.calculation_run_id, cr.calc_date, cr.release_cutoff,
                   cir.issue_mode, cur.use_start_at, cur.use_end_at,
                   ar.threshold_value, ar.reduce_amount
            FROM coupon_config cc
            JOIN import_batch ib ON ib.import_batch_id=cc.import_batch_id
            JOIN calculation_run cr ON cr.import_batch_id=ib.import_batch_id AND cr.calculation_run_id=?
            LEFT JOIN coupon_issue_rule cir ON cir.coupon_config_id=cc.coupon_config_id
            LEFT JOIN coupon_use_rule cur ON cur.coupon_config_id=cc.coupon_config_id
            LEFT JOIN activity a ON a.import_batch_id=cc.import_batch_id AND a.activity_no=cc.config_no
            LEFT JOIN activity_rule ar ON ar.activity_id=a.activity_id
            WHERE cc.coupon_config_id=?
            """,
            (calc_batch_id, coupon_config_id),
        ).fetchone()
        if header is None:
            raise KeyError(f"coupon {coupon_config_id} run {calc_batch_id}")
        orders = list(connection.execute(
            """
            SELECT oh.order_id, oh.order_no, oh.order_time, oh.customer_no, oh.customer_name, oh.salesperson,
                   oh.order_status, oh.order_source, oh.order_type, oh.payment_method,
                   (SELECT SUM(ol.pre_discount_amount) FROM order_line ol WHERE ol.order_id=oh.order_id) AS product_amount,
                   (SELECT SUM(ol.discount_amount) FROM order_line ol WHERE ol.order_id=oh.order_id) AS order_discount,
                   red.discount_amount AS coupon_benefit, red.coupon_no, red.status, red.receive_time, red.used_at,
                   rc.is_candidate, rc.reason, ec.theoretical_coupon_benefit, ec.consistency
            FROM coupon_redemption red
            JOIN order_header oh ON oh.order_id=red.order_id
            JOIN release_candidate rc ON rc.order_id=oh.order_id AND rc.calculation_run_id=?
            JOIN entitlement_check ec ON ec.order_id=oh.order_id AND ec.calculation_run_id=?
            WHERE red.import_batch_id=?
            ORDER BY oh.order_time, oh.order_no
            """,
            (calc_batch_id, calc_batch_id, header["import_batch_id"]),
        ))
        coupon_total = sum(float(row["coupon_benefit"] or 0) for row in orders)
        released = sum(float(row["coupon_benefit"] or 0) for row in orders if row["is_candidate"])
        theoretical = sum(float(row["theoretical_coupon_benefit"] or 0) for row in orders)
        consistent = sum(1 for row in orders if row["consistency"] == "一致")
        period = ""
        if header["use_start_at"] or header["use_end_at"]:
            period = f"{header['use_start_at'] or ''} ~ {header['use_end_at'] or ''}"
        threshold = ""
        if header["threshold_value"] not in (None, "") and header["reduce_amount"] not in (None, ""):
            threshold = f"满 {header['threshold_value']} 减 {header['reduce_amount']}"
        workbook = Workbook()
        cover = workbook.active
        cover.title = "活动核验结论"
        _write_cover(cover, "EC101 活动费用核验报告", "一份报告 = 一张券配置 × 一次核算。计费只认本券核销；同单活动优惠不进本报告费用。", [
            ("经销商名称", header["dealer_name"]),
            ("平台名称", header["platform_name"]),
            ("活动编号", header["config_no"]),
            ("活动名称", header["coupon_name"]),
            ("活动类型", "优惠券"),
            ("优惠券配置编号", header["config_no"]),
            ("优惠券编号", orders[0]["coupon_no"] if orders else ""),
            ("券类型 / 状态", f"{header['coupon_type'] or ''} / {(orders[0]['status'] if orders else header['config_status']) or ''}"),
            ("发放方式", header["issue_mode"] or ""),
            ("使用期限", period),
            ("门槛", threshold),
            ("数据期间", f"{header['coverage_start'] or ''} 至 {header['coverage_end'] or ''}"),
            ("核算日", header["calc_date"]),
            ("释放截止时刻", header["release_cutoff"]),
            ("参与订单数", len(orders)),
            ("可释放订单数", sum(1 for row in orders if row["is_candidate"])),
            ("待释放订单数", sum(1 for row in orders if not row["is_candidate"])),
            ("活动优惠合计（核销）", None),
            ("优惠券优惠合计", _money(coupon_total)),
            ("可释放金额", _money(released)),
            ("待释放金额", _money(coupon_total - released)),
            ("理论权益合计", _money(theoretical)),
            ("一致订单数", f"{consistent} / {len(orders)}"),
            ("计费口径", "只按本券核销优惠金额；不按订单行优惠，不用规则替换费用"),
            ("释放口径", "订单状态=已完成，且下单时间早于释放截止时刻"),
        ])
        order_rows = []
        for index, row in enumerate(orders, start=1):
            coupon_fee = _money(row["coupon_benefit"])
            theoretical_fee = _money(row["theoretical_coupon_benefit"])
            difference = ""
            if coupon_fee != "" and theoretical_fee != "":
                difference = round(float(coupon_fee) - float(theoretical_fee), 2)
            order_rows.append([
                index, header["dealer_name"], header["platform_name"], header["config_no"], header["coupon_name"],
                "优惠券", header["calc_date"], header["release_cutoff"], row["order_no"], row["order_time"],
                row["customer_no"], row["customer_name"], row["salesperson"] or "", row["order_status"],
                row["order_source"] or "", row["order_type"] or "", row["payment_method"] or "",
                _money(row["product_amount"]), _money(row["order_discount"]), "",
                coupon_fee, "",
                "是" if row["is_candidate"] else "否", row["reason"],
                theoretical_fee, row["consistency"] or "", difference,
            ])
        sheet = workbook.create_sheet("参与订单明细")
        _write_orders(sheet, "一行一张用了本券的订单。活动优惠金额留空。计费用「优惠券优惠金额」。", order_rows)
        _write_lines(workbook.create_sheet("订单商品行（附录）"), _order_lines(connection, [row["order_id"] for row in orders]))
        filename = f"核验报告-{header['coupon_name']}-{header['calc_date']}.xlsx"
        return _save(workbook), filename
    finally:
        connection.close()


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "report.xlsx"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
