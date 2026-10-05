import tempfile
import unittest
from pathlib import Path

from api.server import get_import, list_imports
from mvp.import_service import create_database


class ImportQueryTests(unittest.TestCase):
    def test_import_batches_are_listed_and_detail_is_available(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            create_database(path)
            import sqlite3
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO import_batch(snapshot_key,dealer_name,platform_name,template_version,converter_version,imported_at,status,is_current) VALUES ('s1','D1','快马','v1','v1','2026-01-01','calculated',1)")
                connection.commit()
            rows = list_imports(path)
            self.assertEqual(rows["total"], 1)
            self.assertEqual(get_import(path, 1)["dealer_name"], "D1")


if __name__ == "__main__":
    unittest.main()
