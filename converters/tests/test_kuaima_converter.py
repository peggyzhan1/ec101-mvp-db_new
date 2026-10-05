import tempfile
import unittest
from pathlib import Path

from converters.common import ConversionRequest
from converters.kuaima import convert_kuaima
from mvp.standard_workbook import read_standard_workbook


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "快马-兴路强-试点"


class KuaimaConverterTests(unittest.TestCase):
    def test_real_sample_generates_reviewed_standard_workbook(self):
        request = ConversionRequest(
            platform="快马",
            dealer_name="深圳市兴路强商贸有限公司",
            source_paths={
                "customer": [BASE / "User-202609221722.xlsx"],
                "product": [BASE / "Product-202609141043.xlsx"],
                "order_detail": [BASE / "满减/快马-兴路强-满减-订单明细-20260831-20260917.xls"],
                "activity_execution": [BASE / "满减/快马-兴路强-满减-活动明细-20260831-20260917.xls"],
                "coupon_redemption": [BASE / "优惠券/快马-兴路强-优惠券-test1优惠券-活动明细-20260909-20260912.xls"],
            },
            activity_inputs=[{
                "活动编号": "KM-MJ-001", "活动名称": "可口可乐满减", "活动类型": "满减",
                "开始时间": "2026-08-31 10:58:00", "结束时间": "2026-09-17 23:59:00", "活动状态": "已结束",
            }],
            coupon_inputs=[],
            output_dir=Path(tempfile.mkdtemp()),
        )
        result = convert_kuaima(request)
        workbook = read_standard_workbook(result.workbook_path)
        self.assertGreater(result.counts["标准客户"], 0)
        self.assertGreater(result.counts["标准商品"], 0)
        self.assertGreater(result.counts["标准订单明细"], 0)
        self.assertEqual(workbook.tables["标准活动"][0]["活动编号"], "KM-MJ-001")
        self.assertTrue(result.sources_zip_path.exists())


if __name__ == "__main__":
    unittest.main()
