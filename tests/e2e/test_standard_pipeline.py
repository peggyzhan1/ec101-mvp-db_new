import sqlite3
import tempfile
import unittest
from pathlib import Path

from converters.common import ConversionRequest
from converters.kuaima import convert_kuaima
from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_workbook import read_standard_workbook


class StandardPipelineTests(unittest.TestCase):
    def test_kuaima_source_to_standard_to_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, headers, row):
                path = root / name
                cells = lambda values: "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>"
                path.write_text("<table>" + cells(headers) + cells(row) + "</table>", encoding="utf-8")
                return path
            customer = write("customer.csv", ["客户编号", "客户名称"], ["C1", "客户1"])
            product = write("product.csv", ["商品编号", "商品名称"], ["P1", "商品1"])
            order = write("order.csv", ["订单编号", "下单时间", "客户编号", "客户名称", "商品编号", "商品名称", "订货数量", "订货金额", "订单状态"], ["O1", "2026-01-01", "C1", "客户1", "P1", "商品1", "2", "20", "已完成"])
            result = convert_kuaima(ConversionRequest("快马", "测试经销商", {"customer": [customer], "product": [product], "order_detail": [order]}, [], [], root / "output"))
            workbook = read_standard_workbook(result.workbook_path)
            db_path = root / "ec101.db"; create_database(db_path)
            with sqlite3.connect(db_path) as connection:
                imported = import_snapshot(connection, workbook, ArchiveMetadata(str(result.sources_zip_path), "hash", result.sources_zip_path.stat().st_size))
                self.assertEqual(imported.status, "calculated")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM order_header").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
