import tempfile
import unittest
from pathlib import Path

from converters.common import ConversionRequest
from converters.zhoupu import convert_zhoupu
from mvp.standard_workbook import read_standard_workbook


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "舟谱-羿柏-试点"


class ZhoupuConverterTests(unittest.TestCase):
    def test_real_sample_uses_row_four_headers_and_preserves_downstream_order(self):
        request = ConversionRequest(
            platform="舟谱",
            dealer_name="深圳市翌柏商贸有限公司",
            source_paths={
                "customer": [BASE / "客户档案-20260914.xlsx"],
                "product": [BASE / "商品档案-20260914.xlsx"],
                "order_detail": [BASE / "满减/舟谱-羿柏-订单明细 0826-0827.xlsx"],
                "fulfillment": [BASE / "满减/舟谱-羿柏-订单明细-XD-20260826-20260908.xlsx"],
            },
            activity_inputs=[],
            coupon_inputs=[],
            output_dir=Path(tempfile.mkdtemp()),
        )
        result = convert_zhoupu(request)
        workbook = read_standard_workbook(result.workbook_path)
        orders = workbook.tables["标准订单明细"]
        self.assertGreater(len(orders), 0)
        self.assertTrue(orders[0]["单据编号"].startswith("SXD"))
        self.assertTrue(orders[0]["下游订单编号"].startswith("XD"))
        self.assertEqual(orders[0]["支付方式"], "")


if __name__ == "__main__":
    unittest.main()
