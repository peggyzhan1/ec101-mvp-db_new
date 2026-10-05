import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from api.server import import_uploaded_files
from mvp.import_service import create_database
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import StandardWorkbook, write_standard_workbook


class ImportApiTests(unittest.TestCase):
    def test_uploaded_standard_workbook_is_imported_and_calculated(self):
        workbook = StandardWorkbook(
            tables={sheet: [] for sheet in STANDARD_SHEETS[1:]},
            manifest={
                "模板版本": "v1", "转换工具版本": "v1", "经销商名称": "测试经销商", "平台名称": "快马",
                "数据开始日期": "2026-01-01", "数据结束日期": "2026-01-31", "生成时间": "2026-02-01 00:00:00",
            },
        )
        source_bytes = io.BytesIO()
        with zipfile.ZipFile(source_bytes, "w") as archive:
            archive.writestr("source.csv", "order_no,amount\nO1,10\n")
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ec101.db"
            workbook_path = Path(directory) / "standard.xlsx"
            write_standard_workbook(workbook_path, workbook.tables, workbook.manifest)
            create_database(db_path)
            payload = import_uploaded_files(db_path, workbook_path.read_bytes(), source_bytes.getvalue(), "sources.zip")
            self.assertEqual(payload["status"], "calculated")
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM import_file").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
