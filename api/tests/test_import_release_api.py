import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from api.server import get_import, get_import_release, import_uploaded_files
from mvp.import_service import create_database
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import StandardWorkbook, write_standard_workbook


def workbook_bytes(directory: Path) -> bytes:
    tables = {sheet: [] for sheet in STANDARD_SHEETS[1:]}
    tables.update({
        "标准客户": [{"客户编号": "C1", "客户名称": "客户一"}],
        "标准商品": [{"商品编号": "P1", "商品名称": "可乐"}],
        "标准订单明细": [
            {"单据编号": "O1", "下单时间": "2026-09-01 10:00:00", "客户编号": "C1", "客户名称": "客户一", "商品编号": "P1", "数量": "1", "实付金额": "285", "订单状态": "已完成"},
            {"单据编号": "O2", "下单时间": "2026-09-21 10:00:00", "客户编号": "C1", "客户名称": "客户一", "商品编号": "P1", "数量": "1", "实付金额": "285", "订单状态": "已完成"},
        ],
        "标准活动": [{"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "活动类型": "满减"}],
        "标准活动核销明细": [
            {"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "客户编号": "C1", "订单号": "O1", "优惠金额": "15"},
            {"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "客户编号": "C1", "订单号": "O2", "优惠金额": "15"},
        ],
    })
    workbook = StandardWorkbook(tables=tables, manifest={
        "模板版本": "v1", "转换工具版本": "v1", "经销商名称": "测试经销商", "平台名称": "快马",
        "数据开始日期": "2026-09-01", "数据结束日期": "2026-09-21", "生成时间": "2026-09-22 00:00:00",
    })
    path = directory / "standard.xlsx"
    write_standard_workbook(path, workbook.tables, workbook.manifest)
    return path.read_bytes()


class ImportReleaseApiTests(unittest.TestCase):
    def test_upload_honours_calc_date_and_exposes_per_order_release_list(self):
        source = io.BytesIO()
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("订单.xls", "")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "ec101.db"
            create_database(db_path)
            payload = import_uploaded_files(db_path, workbook_bytes(root), source.getvalue(), "sources.zip", calc_date="2026-09-22")
            batch_id = payload["import_batch_id"]
            detail = get_import(db_path, batch_id)
            everything = get_import_release(db_path, batch_id, {})
            pending = get_import_release(db_path, batch_id, {"candidate": "0"})
            searched = get_import_release(db_path, batch_id, {"q": "O1"})
            self.assertIsNone(get_import_release(db_path, 999, {}))
        self.assertEqual(payload["calculation"]["calc_date"], "2026-09-22")
        self.assertEqual((payload["calculation"]["participating_orders"], payload["calculation"]["released_orders"]), (2, 1))
        self.assertEqual(detail["activities"][0]["released_amount"], 15)
        self.assertEqual(everything["total"], 2)
        self.assertEqual(everything["rows"][0]["order_no"], "O1")
        self.assertEqual(everything["rows"][0]["activities"], "可口可乐满减")
        self.assertEqual(pending["rows"][0]["order_no"], "O2")
        self.assertIn("未达T-2", pending["rows"][0]["reason"])
        self.assertEqual(searched["total"], 1)

    def test_invalid_calc_date_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "ec101.db"
            create_database(db_path)
            with self.assertRaises(ValueError):
                import_uploaded_files(db_path, workbook_bytes(root), None, "sources.zip", calc_date="22/09/2026")


if __name__ == "__main__":
    unittest.main()
