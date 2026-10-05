import sqlite3
import tempfile
import unittest
from pathlib import Path

from mvp.import_service import ArchiveMetadata, create_database, import_snapshot, validate_import
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import StandardWorkbook


def workbook_with_rows(**tables):
    all_tables = {sheet: [] for sheet in STANDARD_SHEETS[1:]}
    all_tables.update(tables)
    return StandardWorkbook(
        tables=all_tables,
        manifest={
            "模板版本": "v1", "转换工具版本": "v1", "经销商名称": "测试经销商", "平台名称": "快马",
            "数据开始日期": "2026-01-01", "数据结束日期": "2026-01-31", "生成时间": "2026-02-01 00:00:00",
        },
    )


class ImportServiceTests(unittest.TestCase):
    def test_new_schema_separates_activity_and_coupon_domains(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(any(name.startswith(("raw_", "std_", "tpm_")) for name in tables))
            coupon_fks = {row[2] for row in connection.execute("PRAGMA foreign_key_list(coupon_redemption)")}
            self.assertNotIn("activity", coupon_fks)
            self.assertIn("order_header", coupon_fks)
            connection.execute("INSERT INTO import_batch(snapshot_key, dealer_name, platform_name, template_version, converter_version, imported_at, status) VALUES ('s1', 'D1', '快马', 'v1', 'v1', '2026-02-01', 'calculated')")
            connection.execute("INSERT INTO fulfillment(import_batch_id, order_no, downstream_order_no, fulfillment_status) VALUES (1, 'O1', NULL, '已完成')")
            connection.commit()
            connection.close()

    def test_validation_rejects_orphan_order_customer_and_missing_coupon_config(self):
        workbook = workbook_with_rows(
            **{
                "标准订单明细": [{"单据编号": "O1", "客户编号": "C404", "商品编号": "P1", "实付金额": "10", "订单状态": "已完成"}],
                "标准商品": [{"商品编号": "P1", "商品名称": "商品"}],
                "标准优惠券核销明细": [{"优惠券编号": "C001", "客户编号": "C404", "状态": "已使用", "订单号": "O1"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            issues = validate_import(workbook, connection)
        self.assertIn("missing_customer", {issue.code for issue in issues})

    def test_snapshot_import_is_atomic_and_sums_activity_and_coupon_benefits(self):
        workbook = workbook_with_rows(
            **{
                "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
                "标准商品": [{"商品编号": "P1", "商品名称": "商品"}],
                "标准订单明细": [{"单据编号": "O1", "下单时间": "2026-01-01", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "75", "订单状态": "已完成"}],
                "标准活动": [{"活动编号": "A1", "活动名称": "满减", "活动类型": "满减", "开始时间": "2026-01-01", "结束时间": "2026-01-31", "活动状态": "已结束"}],
                "标准活动核销明细": [{"活动编号": "A1", "活动名称": "满减", "客户编号": "C1", "订单号": "O1", "优惠金额": "15"}],
                "标准优惠券配置": [{"优惠券配置编号": "CC1", "优惠券名称": "券", "配置状态": "有效"}],
                "标准优惠券核销明细": [{"优惠券编号": "C001", "客户编号": "C1", "状态": "已使用", "订单号": "O1", "优惠金额": "10"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            archive = ArchiveMetadata("sources.zip", "sha256", 10)
            result = import_snapshot(connection, workbook, archive)
            row = connection.execute("SELECT activity_benefit, coupon_benefit, total_benefit FROM calculation_run").fetchone()
        self.assertEqual(result.status, "calculated")
        self.assertEqual(row, (15.0, 10.0, 25.0))


if __name__ == "__main__":
    unittest.main()
