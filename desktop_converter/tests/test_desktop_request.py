import tempfile
import unittest
import json
from pathlib import Path

from desktop_converter.app import DesktopApp, build_conversion_request


class DesktopRequestTests(unittest.TestCase):
    def test_required_fields_have_actionable_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "orders.xlsx"
            source.touch()
            with self.assertRaisesRegex(ValueError, "平台"):
                build_conversion_request("", "经销商", {"orders": [source]}, Path(directory))
            with self.assertRaisesRegex(ValueError, "经销商"):
                build_conversion_request("快马", "", {"orders": [source]}, Path(directory))
            with self.assertRaisesRegex(ValueError, "源文件"):
                build_conversion_request("快马", "经销商", {}, Path(directory))

    def test_builds_conversion_request_for_kuaima(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "orders.xlsx"
            source.touch()
            request = build_conversion_request("快马", "经销商", {"orders": [source]}, Path(directory) / "out")
            self.assertEqual(request.platform, "快马")
            self.assertEqual(request.dealer_name, "经销商")
            self.assertEqual(request.source_paths["orders"], [source])

    def test_localized_file_roles_are_normalized_for_converters(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "orders.xlsx"
            source.touch()
            request = build_conversion_request("快马", "经销商", {"客户": [source], "订单": [source]}, Path(directory) / "out")
            self.assertEqual(request.source_paths["customer"], [source])
            self.assertEqual(request.source_paths["order_detail"], [source])

    def test_json_configuration_must_be_an_array(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "activity.json"
            config.write_text(json.dumps({"活动编号": "A1"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "必须是数组"):
                DesktopApp._read_json(str(config), "活动配置")


if __name__ == "__main__":
    unittest.main()
