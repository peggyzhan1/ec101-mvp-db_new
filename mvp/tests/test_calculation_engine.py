import sqlite3
import tempfile
import unittest
from pathlib import Path

from mvp.calculation_engine import calculate_batch, parse_calc_date, release_cutoff, run_calculation
from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import StandardWorkbook

ENGINE = Path(__file__).resolve().parents[1] / "calculation_engine.py"
IMPORT = Path(__file__).resolve().parents[1] / "import_service.py"


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


class CalculationEngineBoundaryTests(unittest.TestCase):
    def test_import_module_does_not_write_result_tables(self):
        source = IMPORT.read_text(encoding="utf-8")
        for table in ("calculation_run", "entitlement_check", "release_candidate", "activity_fee_summary", "calculation_quality_issue"):
            self.assertNotIn(f"INSERT INTO {table}", source, table)

    def test_engine_has_no_platform_branch(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotIn("快马", source)
        self.assertNotIn("舟谱", source)
        self.assertNotIn("if platform", source)

    def test_parse_calc_date_rejects_non_iso(self):
        with self.assertRaises(ValueError):
            parse_calc_date("2026/09/22")
        self.assertEqual(release_cutoff("2026-09-22"), "2026-09-20 00:00:00")

    def test_import_then_calculate_are_separate_steps(self):
        workbook = workbook_with_rows(
            **{
                "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
                "标准商品": [{"商品编号": "P1", "商品名称": "商品"}],
                "标准订单明细": [{"单据编号": "O1", "下单时间": "2026-09-01", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "75", "订单状态": "已完成"}],
                "标准活动": [{"活动编号": "A1", "活动名称": "满减", "活动类型": "满减"}],
                "标准活动核销明细": [{"活动编号": "A1", "活动名称": "满减", "客户编号": "C1", "订单号": "O1", "优惠金额": "15"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            imported = import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "sha256", 10))
            self.assertEqual(imported.status, "imported")
            self.assertEqual(connection.execute("SELECT status FROM import_batch").fetchone()[0], "imported")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM calculation_run").fetchone()[0], 0)
            calc_id = calculate_batch(connection, imported.import_batch_id, "2026-09-22")
            run = run_calculation(connection, imported.import_batch_id)
        self.assertEqual(calc_id, run["calculation_run_id"])
        self.assertEqual((run["activity_benefit"], run["released_activity_benefit"], run["released_orders"]), (15.0, 15.0, 1))
        self.assertEqual((run["theoretical_activity_benefit"], run["consistent_orders"]), (0.0, 0))
        self.assertEqual(connection.execute("SELECT consistency FROM entitlement_check").fetchone()[0], "按核销明细")
        self.assertEqual(connection.execute("SELECT status FROM import_batch").fetchone()[0], "calculated")


class PromotionRecalcTests(unittest.TestCase):
    def test_discount_rule_fills_theoretical_and_keeps_redemption_fees(self):
        workbook = workbook_with_rows(
            **{
                "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
                "标准商品": [{"商品编号": "P1", "商品名称": "商品"}],
                "标准订单明细": [{"单据编号": "O1", "下单时间": "2026-09-01 10:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "优惠前金额": "400", "实付金额": "385", "订单状态": "已完成"}],
                "标准活动": [{"活动编号": "A1", "活动名称": "满减", "活动类型": "满减", "开始时间": "2026-08-31 00:00:00", "结束时间": "2026-09-17 23:59:00"}],
                "标准活动规则": [{"活动编号": "A1", "规则编号": "1", "门槛类型": "金额", "门槛值": "300", "立减金额": "15"}],
                "标准活动核销明细": [{"活动编号": "A1", "活动名称": "满减", "客户编号": "C1", "订单号": "O1", "商品总金额": "400", "优惠金额": "15"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            imported = import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "sha256", 10))
            calculate_batch(connection, imported.import_batch_id, "2026-09-22")
            run = run_calculation(connection, imported.import_batch_id)
            check = connection.execute("SELECT consistency, theoretical_activity_benefit, activity_benefit FROM entitlement_check").fetchone()
        self.assertEqual((run["activity_benefit"], run["released_activity_benefit"]), (15.0, 15.0))
        self.assertEqual((run["theoretical_activity_benefit"], run["consistent_orders"]), (15.0, 1))
        self.assertEqual(tuple(check), ("一致", 15.0, 15.0))

    def test_mismatch_is_差异_but_does_not_block_release(self):
        workbook = workbook_with_rows(
            **{
                "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
                "标准商品": [{"商品编号": "P1", "商品名称": "商品"}],
                "标准订单明细": [{"单据编号": "O1", "下单时间": "2026-09-01 10:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "优惠前金额": "400", "实付金额": "390", "订单状态": "已完成"}],
                "标准活动": [{"活动编号": "A1", "活动名称": "满减", "活动类型": "满减", "开始时间": "2026-08-31 00:00:00", "结束时间": "2026-09-17 23:59:00"}],
                "标准活动规则": [{"活动编号": "A1", "规则编号": "1", "门槛类型": "金额", "门槛值": "300", "立减金额": "15"}],
                "标准活动核销明细": [{"活动编号": "A1", "活动名称": "满减", "客户编号": "C1", "订单号": "O1", "商品总金额": "400", "优惠金额": "10"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            imported = import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "sha256", 10))
            calculate_batch(connection, imported.import_batch_id, "2026-09-22")
            run = run_calculation(connection, imported.import_batch_id)
            check = connection.execute("SELECT consistency, is_candidate FROM entitlement_check JOIN release_candidate USING (calculation_run_id, order_id)").fetchone()
            issues = [tuple(row) for row in connection.execute("SELECT issue_type, level FROM calculation_quality_issue")]
        self.assertEqual(run["released_activity_benefit"], 10.0)
        self.assertEqual(tuple(check), ("差异", 1))
        self.assertIn(("理论权益与实际执行不一致", "警告"), issues)

    def test_coupon_activity_without_executions_is_omitted_from_fee_summary(self):
        workbook = workbook_with_rows(
            **{
                "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
                "标准商品": [{"商品编号": "P1", "商品名称": "商品"}],
                "标准订单明细": [{"单据编号": "O1", "下单时间": "2026-09-01 10:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "优惠前金额": "400", "实付金额": "385", "订单状态": "已完成"}],
                "标准活动": [
                    {"活动编号": "A1", "活动名称": "满减", "活动类型": "满减", "开始时间": "2026-08-31 00:00:00", "结束时间": "2026-09-17 23:59:00"},
                    {"活动编号": "KM-COUPON-AUTO-001", "活动名称": "test1", "活动类型": "满一定金额立减"},
                ],
                "标准活动规则": [
                    {"活动编号": "A1", "规则编号": "1", "门槛类型": "金额", "门槛值": "300", "立减金额": "15"},
                    {"活动编号": "KM-COUPON-AUTO-001", "规则编号": "1", "门槛类型": "金额", "门槛值": "588", "立减金额": "200"},
                ],
                "标准活动核销明细": [{"活动编号": "A1", "活动名称": "满减", "客户编号": "C1", "订单号": "O1", "商品总金额": "400", "优惠金额": "15"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            imported = import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "sha256", 10))
            calculate_batch(connection, imported.import_batch_id, "2026-09-22")
            names = [row[0] for row in connection.execute("SELECT a.activity_name FROM activity_fee_summary s JOIN activity a ON a.activity_id=s.activity_id")]
        self.assertEqual(names, ["满减"])

    def test_gift_counts_quantity_not_currency(self):
        workbook = workbook_with_rows(
            **{
                "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
                "标准商品": [{"商品编号": "348721357", "商品名称": "抱枕"}],
                "标准订单明细": [{"单据编号": "O1", "下单时间": "2026-08-20 10:00:00", "客户编号": "C1", "商品编号": "348721357", "数量": "1", "优惠前金额": "120", "实付金额": "120", "订单状态": "已完成"}],
                "标准活动": [{"活动编号": "G1", "活动名称": "满赠优惠", "活动类型": "满赠", "开始时间": "2026-08-19 00:00:00", "结束时间": "2026-08-31 23:59:00"}],
                "标准活动规则": [{"活动编号": "G1", "规则编号": "1", "门槛类型": "金额", "门槛值": "100", "立减金额": "0"}],
                "标准活动权益": [{"活动编号": "G1", "规则编号": "1", "权益编号": "2", "权益类型": "赠品", "赠品商品编号": "348721357", "赠品数量": "1"}],
                "标准活动核销明细": [{"活动编号": "G1", "活动名称": "满赠优惠", "客户编号": "C1", "订单号": "O1", "商品总金额": "120", "优惠金额": "0"}],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "new.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            imported = import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "sha256", 10))
            calculate_batch(connection, imported.import_batch_id, "2026-09-22")
            run = run_calculation(connection, imported.import_batch_id)
            check = connection.execute("SELECT consistency, gift_qty_entitled, gift_qty_actual, theoretical_activity_benefit FROM entitlement_check").fetchone()
        self.assertEqual((run["activity_benefit"], run["released_activity_benefit"]), (0.0, 0.0))
        self.assertEqual(tuple(check), ("一致", 1.0, 1.0, 0.0))


if __name__ == "__main__":
    unittest.main()
