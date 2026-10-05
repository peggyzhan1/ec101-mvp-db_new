import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.server import get_detail, query_dataset
from mvp.import_service import create_database


class NewBusinessApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.path = Path(self.directory.name) / "standard.db"; create_database(self.path)
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO import_batch(snapshot_key,dealer_name,platform_name,template_version,converter_version,imported_at,status,is_current) VALUES ('s1','D1','快马','v1','v1','2026-01-01','calculated',1)")
            dp = connection.execute("INSERT INTO dealer_platform(dealer_name,platform_name) VALUES ('D1','快马') RETURNING dealer_platform_id").fetchone()[0]
            connection.execute("INSERT INTO customer(import_batch_id,dealer_platform_id,customer_no,customer_name) VALUES (1,?,?,?)", (dp, "C1", "客户1"))
            connection.execute("INSERT INTO product(import_batch_id,dealer_platform_id,product_no,product_name) VALUES (1,?,?,?)", (dp, "P1", "商品1"))
            connection.execute("INSERT INTO order_header(import_batch_id,dealer_platform_id,order_no,customer_no,order_status) VALUES (1,?,?,?,?)", (dp, "O1", "C1", "已完成"))
            connection.commit()

    def tearDown(self): self.directory.cleanup()

    def test_orders_and_detail_read_new_schema(self):
        result = query_dataset(self.path, "orders", {})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["order_no"], "O1")
        self.assertEqual(get_detail(self.path, "orders", "1")["customer"], "客户1")


if __name__ == "__main__": unittest.main()
