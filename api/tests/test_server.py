import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.server import SUPPORTED_OBJECTS, ensure_database, get_detail, import_uploaded_files, list_imports, query_dataset, schema_differences
from api.tests.test_import_release_api import workbook_bytes
from mvp.import_service import create_database


class StandardBusinessDataApiTests(unittest.TestCase):
    """业务数据接口读取标准库（mvp/ec101_standard.db 的结构），默认只看当前有效批次。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "ec101_standard.db"
        create_database(self.db_path)
        self.batch_id = import_uploaded_files(self.db_path, workbook_bytes(self.root), None, "sources.zip", calc_date="2026-09-22")["import_batch_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_exposes_standard_business_objects(self):
        self.assertEqual(
            set(SUPPORTED_OBJECTS),
            {"orders", "order-lines", "activities", "activity-executions", "coupon-redemptions", "customers", "products", "fulfillments"},
        )
        for object_name in SUPPORTED_OBJECTS:
            query_dataset(self.db_path, object_name, {"limit": 5})

    def test_orders_carry_promotions_and_support_filters(self):
        result = query_dataset(self.db_path, "orders", {"dealer": "测试经销商", "platform": "快马", "limit": 1, "offset": 0})
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["rows"][0]["order_no"], "O1")
        self.assertEqual(result["rows"][0]["activities"], "可口可乐满减")
        self.assertEqual(result["rows"][0]["line_count"], 1)
        self.assertEqual(query_dataset(self.db_path, "orders", {"dealer": "不存在"})["total"], 0)
        self.assertEqual(query_dataset(self.db_path, "orders", {"q": "O2"})["total"], 1)

    def test_order_detail_includes_lines_executions_and_release(self):
        order_id = query_dataset(self.db_path, "orders", {"q": "O1"})["rows"][0]["id"]
        detail = get_detail(self.db_path, "orders", str(order_id))
        self.assertEqual(len(detail["lines"]), 1)
        self.assertEqual(detail["activity_executions"][0]["discount_amount"], 15)
        self.assertEqual(detail["release"]["is_candidate"], 1)
        self.assertEqual(detail["release"]["calc_date"], "2026-09-22")
        self.assertEqual(detail["entitlement"]["consistency"], "按核销明细")
        self.assertIsNone(get_detail(self.db_path, "orders", "999"))

    def test_only_current_batch_is_visible_by_default(self):
        superseded = self.batch_id
        current = import_uploaded_files(self.db_path, workbook_bytes(self.root), None, "sources.zip", calc_date="2026-09-22")["import_batch_id"]
        rows = {row["import_batch_id"]: row for row in list_imports(self.db_path)["rows"]}
        self.assertEqual((rows[superseded]["is_current"], rows[current]["is_current"]), (0, 1))
        self.assertEqual(rows[current]["order_count"], 2)
        self.assertEqual(query_dataset(self.db_path, "orders", {})["total"], 2)
        self.assertEqual(query_dataset(self.db_path, "orders", {"import_batch_id": superseded})["total"], 2)
        self.assertEqual({row["import_batch_id"] for row in query_dataset(self.db_path, "order-lines", {})["rows"]}, {current})

    def test_unknown_object_is_rejected(self):
        with self.assertRaises(KeyError):
            query_dataset(self.db_path, "drop-table", {"limit": 10, "offset": 0})


class EnsureDatabaseTests(unittest.TestCase):
    def test_fresh_database_matches_ddl(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ec101_standard.db"
            self.assertIsNone(ensure_database(db_path))
            self.assertTrue(db_path.exists())
            self.assertEqual(schema_differences(db_path), [])
            self.assertIsNone(ensure_database(db_path))

    def test_old_schema_file_is_backed_up_and_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ec101_standard.db"
            create_database(db_path)
            with sqlite3.connect(db_path) as connection:
                connection.executescript("DROP TABLE calculation_run; CREATE TABLE calculation_run (calculation_run_id INTEGER PRIMARY KEY, import_batch_id INTEGER NOT NULL, status TEXT NOT NULL);")
            self.assertTrue(any("calculation_run" in problem for problem in schema_differences(db_path)))
            backup = ensure_database(db_path)
            self.assertIsNotNone(backup)
            self.assertTrue(Path(backup).exists())
            self.assertEqual(schema_differences(db_path), [])


if __name__ == "__main__":
    unittest.main()
