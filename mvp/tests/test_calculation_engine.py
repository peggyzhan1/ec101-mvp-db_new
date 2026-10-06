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
        self.assertEqual(connection.execute("SELECT status FROM import_batch").fetchone()[0], "calculated")


if __name__ == "__main__":
    unittest.main()
