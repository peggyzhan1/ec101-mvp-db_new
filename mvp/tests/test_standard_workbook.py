import tempfile
import unittest
from pathlib import Path

import zipfile

from mvp.standard_workbook import read_standard_workbook, write_standard_workbook, write_standard_workbook_fast
from mvp.standard_schema import STANDARD_SHEETS


class StandardWorkbookTests(unittest.TestCase):
    def test_round_trip_keeps_empty_sheets_and_long_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "standard.xlsx"
            write_standard_workbook(
                path,
                {"标准客户": [{"客户编号": "WX-00000000000007507893", "客户名称": "测试客户"}]},
                {"模板版本": "v1", "平台名称": "快马"},
            )
            workbook = read_standard_workbook(path)

        self.assertEqual(tuple(workbook.tables), STANDARD_SHEETS[1:])
        self.assertEqual(workbook.tables["标准客户"][0]["客户编号"], "WX-00000000000007507893")
        self.assertEqual(workbook.tables["标准商品"], [])
        self.assertEqual(workbook.manifest["模板版本"], "v1")

    def test_fast_writer_keeps_rows_that_contain_blank_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "standard.xlsx"
            write_standard_workbook_fast(
                path,
                {"标准客户": [{"客户编号": "C001", "客户名称": "测试客户", "客户类型": ""}]},
                {"模板版本": "v1", "平台名称": "舟谱", "生成时间": ""},
            )
            workbook = read_standard_workbook(path)
            sheet = zipfile.ZipFile(path).read("xl/worksheets/sheet2.xml")

        customer = workbook.tables["标准客户"][0]
        self.assertEqual(customer["客户编号"], "C001")
        self.assertEqual(customer["客户类型"], "")
        self.assertEqual(customer["所属业务员"], "")
        self.assertNotIn(b't="inlineStr" />', sheet)
        self.assertNotIn(b't="inlineStr"/>', sheet)
        self.assertIn(b'<dimension ref="A1:H2"/>', sheet)


if __name__ == "__main__":
    unittest.main()
