"""Atomic import and calculation service for the reviewed standard workbook."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .result_service import calculate_results
from .standard_schema import Issue, validate_rows
from .standard_workbook import StandardWorkbook


@dataclass(frozen=True)
class ArchiveMetadata:
    file_path: str
    sha256: str
    file_size: int


@dataclass(frozen=True)
class ImportResult:
    import_batch_id: int
    calculation_run_id: int
    status: str


class ImportValidationError(ValueError):
    def __init__(self, issues: list[Issue]):
        super().__init__(f"标准数据校验失败: {len(issues)} 项")
        self.issues = issues


def create_database(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    ddl = Path(__file__).with_name("ddl") / "ec101_standard_sqlite.sql"
    connection.executescript(ddl.read_text(encoding="utf-8"))
    connection.commit()
    connection.close()


def _issue(code: str, sheet: str, row: int, column: str | None, message: str) -> Issue:
    return Issue(code, sheet, row, column, message)


def validate_import(workbook: StandardWorkbook, db: sqlite3.Connection) -> list[Issue]:
    issues: list[Issue] = []
    for sheet, rows in workbook.tables.items():
        issues.extend(validate_rows(sheet, rows))
    customer_nos = {row.get("客户编号", "") for row in workbook.tables.get("标准客户", [])}
    product_nos = {row.get("商品编号", "") for row in workbook.tables.get("标准商品", [])}
    order_nos = {row.get("单据编号", "") for row in workbook.tables.get("标准订单明细", [])}
    activity_nos = {row.get("活动编号", "") for row in workbook.tables.get("标准活动", [])}
    seen_orders: set[str] = set()
    for row_number, row in enumerate(workbook.tables.get("标准订单明细", []), start=2):
        order_no = row.get("单据编号", "")
        if order_no in seen_orders:
            continue
        seen_orders.add(order_no)
        if row.get("客户编号", "") not in customer_nos:
            issues.append(_issue("missing_customer", "标准订单明细", row_number, "客户编号", "客户编号不存在"))
        if row.get("商品编号", "") not in product_nos:
            issues.append(_issue("missing_product", "标准订单明细", row_number, "商品编号", "商品编号不存在"))
    for row_number, row in enumerate(workbook.tables.get("标准活动核销明细", []), start=2):
        if row.get("活动编号", "") not in activity_nos:
            issues.append(_issue("missing_activity", "标准活动核销明细", row_number, "活动编号", "活动编号不存在"))
        if row.get("订单号", "") not in order_nos:
            issues.append(_issue("missing_order", "标准活动核销明细", row_number, "订单号", "订单号不存在"))
    for row_number, row in enumerate(workbook.tables.get("标准优惠券核销明细", []), start=2):
        if row.get("订单号") and row.get("订单号") not in order_nos:
            issues.append(_issue("missing_order", "标准优惠券核销明细", row_number, "订单号", "订单号不存在"))
    return issues


def _f(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def import_snapshot(db: sqlite3.Connection, workbook: StandardWorkbook, archive: ArchiveMetadata, calc_date: str | None = None) -> ImportResult:
    issues = validate_import(workbook, db)
    if issues:
        raise ImportValidationError(issues)
    manifest = workbook.manifest
    snapshot_key = uuid.uuid4().hex
    with db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            "UPDATE import_batch SET is_current=0 WHERE dealer_name=? AND platform_name=? AND coverage_start IS ? AND coverage_end IS ?",
            (manifest["经销商名称"], manifest["平台名称"], manifest.get("数据开始日期") or None, manifest.get("数据结束日期") or None),
        )
        batch_id = db.execute(
            "INSERT INTO import_batch(snapshot_key,dealer_name,platform_name,coverage_start,coverage_end,template_version,converter_version,imported_at,status,is_current) VALUES(?,?,?,?,?,?,?,?,?,0)",
            (snapshot_key, manifest["经销商名称"], manifest["平台名称"], manifest.get("数据开始日期") or None,
             manifest.get("数据结束日期") or None, manifest["模板版本"], manifest["转换工具版本"], datetime.now().isoformat(timespec="seconds"), "importing"),
        ).lastrowid
        db.execute("INSERT INTO import_file(import_batch_id,file_role,file_path,sha256,file_size) VALUES(?,?,?,?,?)",
                   (batch_id, "sources", archive.file_path, archive.sha256, archive.file_size))
        dealer_platform_id = db.execute(
            "INSERT INTO dealer_platform(dealer_name,platform_name) VALUES(?,?) ON CONFLICT(dealer_name,platform_name) DO UPDATE SET dealer_name=excluded.dealer_name RETURNING dealer_platform_id",
            (manifest["经销商名称"], manifest["平台名称"]),
        ).fetchone()[0]
        for row in workbook.tables.get("标准客户", []):
            db.execute("INSERT INTO customer(import_batch_id,dealer_platform_id,customer_no,customer_name,customer_type,customer_region,address,phone,added_at,salesperson) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (batch_id, dealer_platform_id, row["客户编号"], row["客户名称"], row.get("客户类型"), row.get("客户区域"), row.get("详细地址"), row.get("联系电话"), row.get("添加时间"), row.get("所属业务员")))
        for row in workbook.tables.get("标准商品", []):
            db.execute("INSERT INTO product(import_batch_id,dealer_platform_id,product_no,product_name,brand,category,barcode,spec,base_unit,box_conversion,base_qty_per_box) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (batch_id, dealer_platform_id, row["商品编号"], row["商品名称"], row.get("商品品牌"), row.get("商品目录"), row.get("商品条码"), row.get("商品规格"), row.get("基本单位"), row.get("箱规"), _f(row.get("每箱基本单位数量"))))
        order_ids: dict[str, int] = {}
        for row in workbook.tables.get("标准订单明细", []):
            order_no = row["单据编号"]
            if order_no not in order_ids:
                order_ids[order_no] = db.execute("INSERT INTO order_header(import_batch_id,dealer_platform_id,order_no,order_time,customer_no,customer_name,salesperson,order_source,order_type,order_status,payment_method,downstream_order_no) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (batch_id, dealer_platform_id, order_no, row.get("下单时间"), row["客户编号"], row.get("客户名称"), row.get("业务员"), row.get("订单来源"), row.get("订单类型"), row["订单状态"], row.get("支付方式"), row.get("下游订单编号"))).lastrowid
            db.execute("INSERT INTO order_line(order_id,product_no,product_name,category,spec,barcode,unit,quantity,pre_discount_amount,activity_numbers,coupon_numbers,discount_amount,paid_amount,unit_price,return_qty) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (order_ids[order_no], row["商品编号"], row.get("商品名称"), row.get("商品目录"), row.get("规格"), row.get("商品条码"), row.get("单位"), _f(row.get("数量")), _f(row.get("优惠前金额")), row.get("活动编号"), row.get("优惠券编号"), _f(row.get("优惠金额")), _f(row.get("实付金额")), _f(row.get("单价")), _f(row.get("退货数量"))))
        activity_ids: dict[str, int] = {}
        for row in workbook.tables.get("标准活动", []):
            activity_ids[row["活动编号"]] = db.execute("INSERT INTO activity(import_batch_id,activity_no,activity_name,activity_type,promo_method,start_time,end_time,allow_activity_stack,allow_coupon_stack,activity_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (batch_id, row["活动编号"], row["活动名称"], row["活动类型"], row.get("促销方式"), row["开始时间"], row["结束时间"], row.get("是否允许叠加活动"), row.get("是否允许叠加优惠券"), row["活动状态"])).lastrowid
        for row in workbook.tables.get("标准活动规则", []):
            db.execute("INSERT INTO activity_rule(activity_id,rule_no,threshold_type,threshold_value,reduce_amount,free_shipping) VALUES(?,?,?,?,?,?)",
                       (activity_ids[row["活动编号"]], row["规则编号"], row["门槛类型"], _f(row.get("门槛值")), _f(row.get("立减金额")), 1 if row.get("是否免邮") in ("1", "是", "true") else 0))
        for row in workbook.tables.get("标准活动权益", []):
            db.execute("INSERT INTO activity_benefit(activity_id,rule_no,benefit_no,benefit_type,gift_product_no,gift_product_name,gift_qty,gift_unit) VALUES(?,?,?,?,?,?,?,?)",
                       (activity_ids[row["活动编号"]], row["规则编号"], row["权益编号"], row["权益类型"], row.get("赠品商品编号"), row.get("赠品商品名称"), _f(row.get("赠品数量")), row.get("赠品单位")))
        for row in workbook.tables.get("标准活动范围", []):
            db.execute("INSERT INTO activity_scope(activity_id,scope_no,scope_category,scope_dimension,scope_value) VALUES(?,?,?,?,?)",
                       (activity_ids[row["活动编号"]], row["范围编号"], row["范围类别"], row["范围维度"], row["范围值"]))
        for row in workbook.tables.get("标准活动核销明细", []):
            db.execute("INSERT INTO activity_execution(activity_id,order_id,activity_name,customer_no,customer_name,salesperson,product_amount,discount_amount) VALUES(?,?,?,?,?,?,?,?)",
                       (activity_ids[row["活动编号"]], order_ids[row["订单号"]], row.get("活动名称"), row.get("客户编号"), row.get("客户"), row.get("所属业务员"), _f(row.get("商品总金额")), _f(row.get("优惠金额"))))
        coupon_config_ids: dict[str, int] = {}
        for row in workbook.tables.get("标准优惠券配置", []):
            coupon_config_ids[row["优惠券配置编号"]] = db.execute("INSERT INTO coupon_config(import_batch_id,config_no,coupon_name,coupon_type,config_status) VALUES(?,?,?,?,?)",
                (batch_id, row["优惠券配置编号"], row["优惠券名称"], row.get("券类型"), row["配置状态"])).lastrowid
        for row in workbook.tables.get("标准优惠券发放规则", []):
            db.execute("INSERT INTO coupon_issue_rule(coupon_config_id,issue_mode,issue_start_at,issue_end_at,auto_issue_at,qty_per_issue,max_claim_per_customer,daily_claim_limit,rule_status) VALUES(?,?,?,?,?,?,?,?,?)",
                       (coupon_config_ids[row["优惠券配置编号"]], row["发放方式"], row["发放开始时间"], row.get("发放结束时间"), row.get("自动发放时间"), _f(row.get("每次发放数量")), _f(row.get("每客户领取上限")), _f(row.get("每日领取上限")), row["规则状态"]))
        for row in workbook.tables.get("标准优惠券使用规则", []):
            db.execute("INSERT INTO coupon_use_rule(coupon_config_id,coupon_type,validity_mode,use_start_at,use_end_at,valid_days_after_receive,max_use_per_coupon,rule_status) VALUES(?,?,?,?,?,?,?,?)",
                       (coupon_config_ids[row["优惠券配置编号"]], row["券类型"], row["有效期类型"], row.get("使用开始时间"), row.get("使用结束时间"), int(_f(row.get("领取后有效天数"))), _f(row.get("每张券最多使用次数")), row["规则状态"]))
        for row in workbook.tables.get("标准优惠券适用范围", []):
            db.execute("INSERT INTO coupon_scope(coupon_config_id,scope_no,scope_category,scope_dimension,scope_value) VALUES(?,?,?,?,?)",
                       (coupon_config_ids[row["优惠券配置编号"]], row["范围编号"], row["范围类别"], row["范围维度"], row["范围值"]))
        for row in workbook.tables.get("标准优惠券核销明细", []):
            db.execute("INSERT INTO coupon_redemption(import_batch_id,order_id,coupon_no,customer_no,customer_name,salesperson,receive_time,use_period,status,used_at,discount_amount) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (batch_id, order_ids.get(row.get("订单号")), row["优惠券编号"], row["客户编号"], row.get("客户"), row.get("所属业务员"), row.get("领取时间"), row.get("使用期限"), row["状态"], row.get("使用时间"), _f(row.get("优惠金额"))))
        for row in workbook.tables.get("标准履约", []):
            db.execute("INSERT INTO fulfillment(import_batch_id,order_no,downstream_order_no,fulfillment_status,outbound_at,completed_at,settlement_status,return_qty) VALUES(?,?,?,?,?,?,?,?)",
                       (batch_id, row["单据编号"], row.get("下游订单编号"), row["履约订单状态"], row.get("出库时间"), row.get("完成时间"), row.get("结款状态"), _f(row.get("退货数量"))))
        calc_id = calculate_results(db, batch_id, calc_date)
        db.execute("UPDATE import_batch SET status='calculated', is_current=1 WHERE import_batch_id=?", (batch_id,))
    return ImportResult(batch_id, calc_id, "calculated")


def run_calculation(db: sqlite3.Connection, import_batch_id: int) -> dict[str, Any]:
    row = db.execute("SELECT calculation_run_id,activity_benefit,coupon_benefit,total_benefit,status FROM calculation_run WHERE import_batch_id=? ORDER BY calculation_run_id DESC LIMIT 1", (import_batch_id,)).fetchone()
    if row is None:
        raise ValueError("导入批次尚未产生核算结果")
    return {"calculation_run_id": row[0], "activity_benefit": row[1], "coupon_benefit": row[2], "total_benefit": row[3], "status": row[4]}
