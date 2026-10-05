import tempfile
import unittest
from pathlib import Path

from converters.cli import parse_source_arg


class ConverterCliTests(unittest.TestCase):
    def test_parse_source_arg_splits_role_and_path(self):
        role, path = parse_source_arg("customer=/tmp/customers.xlsx")
        self.assertEqual(role, "customer")
        self.assertEqual(path, Path("/tmp/customers.xlsx"))


if __name__ == "__main__":
    unittest.main()
