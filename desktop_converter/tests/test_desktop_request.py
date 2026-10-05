import tempfile
import unittest
from pathlib import Path

from desktop_converter.app import build_conversion_request


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


if __name__ == "__main__":
    unittest.main()
