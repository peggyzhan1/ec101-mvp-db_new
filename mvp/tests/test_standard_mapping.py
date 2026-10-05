import unittest
from pathlib import Path

DDL_PATH = Path(__file__).resolve().parents[1] / "ddl" / "ec101_standard_sqlite.sql"
IMPORT = Path(__file__).resolve().parents[1] / "import_service.py"
DOC = Path(__file__).resolve().parents[2] / "docs" / "标准数据到标准库对照.md"
SVG_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_standard_er_svg.py"


class StandardMappingDocsTests(unittest.TestCase):
    def test_every_imported_sheet_is_documented(self):
        source = IMPORT.read_text(encoding="utf-8")
        doc = DOC.read_text(encoding="utf-8")
        for sheet in (
            "标准客户", "标准商品", "标准订单明细", "标准活动", "标准活动规则", "标准活动权益",
            "标准活动范围", "标准活动核销明细", "标准优惠券配置", "标准优惠券发放规则",
            "标准优惠券使用规则", "标准优惠券适用范围", "标准优惠券核销明细", "标准履约",
        ):
            self.assertIn(f'"{sheet}"', source)
            self.assertIn(sheet, doc)

    def test_er_svg_lists_every_ddl_table(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_standard_er_svg", SVG_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        svg = module.render().read_text(encoding="utf-8")
        tables = [line.split()[2] for line in DDL_PATH.read_text(encoding="utf-8").splitlines() if line.startswith("CREATE TABLE ")]
        self.assertGreaterEqual(len(tables), 20)
        for table in tables:
            self.assertIn(f">{table}<", svg, table)

    def test_er_png_is_generated_in_repo(self):
        png = Path(__file__).resolve().parents[2] / "docs" / "diagrams" / "ec101-standard-er.png"
        self.assertTrue(png.is_file(), png)
        self.assertGreater(png.stat().st_size, 50_000)


if __name__ == "__main__":
    unittest.main()
