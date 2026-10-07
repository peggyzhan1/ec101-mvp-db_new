import unittest
from pathlib import Path

from mvp.standard_workbook import read_standard_workbook

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "samples" / "zhoupu-verified-standard"


class YiboStandardExportTests(unittest.TestCase):
    def test_rebate_workbook_is_yibo_zhoupu_with_redemptions(self):
        workbook = read_standard_workbook(SAMPLES / "返券" / "standard.xlsx")
        self.assertEqual((workbook.manifest["经销商名称"], workbook.manifest["平台名称"]), ("羿柏", "舟谱"))
        self.assertEqual([row["活动名称"] for row in workbook.tables["标准活动"]], ["可口可乐产品288返15元券"])
        self.assertEqual(len(workbook.tables["标准活动核销明细"]), 45)
        self.assertTrue(workbook.tables["标准订单明细"])
        self.assertTrue(all(row["商品编号"] for row in workbook.tables["标准订单明细"]))
        self.assertEqual(workbook.tables["标准优惠券配置"], [])

    def test_gift_workbook_is_yibo_zhoupu_with_redemptions(self):
        workbook = read_standard_workbook(SAMPLES / "满赠" / "standard.xlsx")
        self.assertEqual((workbook.manifest["经销商名称"], workbook.manifest["平台名称"]), ("羿柏", "舟谱"))
        self.assertEqual([row["活动名称"] for row in workbook.tables["标准活动"]], ["雪碧系列满100元送抱枕"])
        self.assertEqual(len(workbook.tables["标准活动核销明细"]), 142)
        self.assertTrue(all(row["优惠金额"] in ("0", "0.0") for row in workbook.tables["标准活动核销明细"]))
