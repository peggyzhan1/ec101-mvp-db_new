import tempfile
import unittest
from pathlib import Path

from converters.common import ConversionRequest
from converters.kuaima import convert_kuaima, infer_activity_type, parse_policy_activity_name
from mvp.standard_workbook import read_standard_workbook


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "快马-兴路强-试点"


def html_table(path: Path, headers, rows) -> Path:
    cells = lambda values: "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>"
    path.write_text("<table>" + cells(headers) + "".join(cells(row) for row in rows) + "</table>", encoding="utf-8")
    return path


class PolicyParsingTests(unittest.TestCase):
    def test_activity_name_is_taken_from_bracketed_policy_text(self):
        self.assertEqual(parse_policy_activity_name("参与[可口可乐满减]组合金额满¥300，立减¥15活动，为您节省¥1.24"), "可口可乐满减")
        self.assertEqual(parse_policy_activity_name("参与[满赠优惠]组合金额满¥100，送赠品活动"), "满赠优惠")
        self.assertEqual(parse_policy_activity_name("  无括号政策  "), "无括号政策")
        self.assertEqual(parse_policy_activity_name(""), "")

    def test_activity_type_is_inferred_from_platform_wording(self):
        self.assertEqual(infer_activity_type("组合金额满¥100，送赠品活动", "满赠优惠"), "满赠")
        self.assertEqual(infer_activity_type("组合金额满¥300，立减¥15活动", "可口可乐满减"), "满减")
        self.assertEqual(infer_activity_type("", "周年庆"), "其他")


class KuaimaExecutionAggregationTests(unittest.TestCase):
    def _convert(self, root: Path, activity_inputs=()):
        customer = html_table(root / "customer.csv", ["客户编号", "客户名称"], [["C1", "客户一"]])
        product = html_table(root / "product.csv", ["商品编号", "商品名称"], [["P1", "可乐"], ["P2", "纸巾"]])
        order = html_table(
            root / "order.csv",
            ["订单编号", "下单时间", "客户编号", "客户名称", "商品编号", "商品名称", "订货数量", "优惠前金额", "优惠金额", "订货金额", "订单状态"],
            [
                ["O1", "2026/9/1 10:00:00", "C1", "客户一", "P1", "可乐", "2", "300", "20", "280", "已完成"],
                ["O1", "2026/9/1 10:00:00", "C1", "客户一", "P2", "纸巾", "1", "100", "95", "5", "已完成"],
                ["O2", "2026/9/2 10:00:00", "C1", "客户一", "P2", "纸巾", "1", "50", "0", "50", "已完成"],
            ],
        )
        activity = html_table(
            root / "activity.csv",
            ["订单号", "客户", "商品总金额", "促销优惠金额", "享受促销政策"],
            [
                ["O1", "客户一", "200.0000", "10.0000", "参与[可口可乐满减]组合金额满¥300，立减¥15活动，为您节省¥10.00"],
                ["O1", "客户一", "100.0000", "5.0000", "参与[可口可乐满减]组合金额满¥300，立减¥15活动，为您节省¥5.00"],
                ["O1", "客户一", "100.0000", "0.0000", "参与[满赠优惠]组合金额满¥100，送赠品活动"],
            ],
        )
        coupon = html_table(
            root / "coupon.csv",
            ["优惠券名称", "优惠券编号", "领取人", "客户编号", "所属业务员", "领取时间", "使用期限", "状态", "使用时间", "使用订单号", "优惠金额"],
            [["test1", "2026090917003", "客户一", "C1", "", "2026/9/1 09:00:00", "2026-09-01-2026-09-12", "已使用", "2026/9/1 10:00:00", "O1", "95.0000"]],
        )
        request = ConversionRequest(
            "快马", "测试经销商",
            {"customer": [customer], "product": [product], "order_detail": [order], "activity_execution": [activity], "coupon_redemption": [coupon]},
            list(activity_inputs), [], root / "out",
        )
        return read_standard_workbook(convert_kuaima(request).workbook_path)

    def test_execution_rows_are_aggregated_per_order_and_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = self._convert(Path(directory))
        execution = {row["活动编号"]: row for row in workbook.tables["标准活动核销明细"]}
        self.assertEqual(set(execution), {"可口可乐满减", "满赠优惠"})
        self.assertEqual(execution["可口可乐满减"]["优惠金额"], "15")
        self.assertEqual(execution["可口可乐满减"]["商品总金额"], "300")
        self.assertEqual(execution["可口可乐满减"]["客户编号"], "C1")
        self.assertEqual(execution["满赠优惠"]["优惠金额"], "0")
        activities = {row["活动编号"]: row for row in workbook.tables["标准活动"]}
        self.assertEqual(activities["可口可乐满减"]["活动类型"], "满减")
        self.assertEqual(activities["满赠优惠"]["活动类型"], "满赠")
        self.assertEqual(activities["可口可乐满减"]["开始时间"], "")

    def test_order_lines_only_echo_numbers_recorded_in_platform_details(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook = self._convert(Path(directory))
        lines = {(row["单据编号"], row["商品编号"]): row for row in workbook.tables["标准订单明细"]}
        self.assertEqual(lines[("O1", "P1")]["活动编号"], "可口可乐满减;满赠优惠")
        self.assertEqual(lines[("O1", "P1")]["优惠券编号"], "2026090917003")
        self.assertEqual(lines[("O1", "P1")]["优惠金额"], "20")
        self.assertEqual(lines[("O2", "P2")]["活动编号"], "")
        self.assertEqual(lines[("O2", "P2")]["优惠券编号"], "")
        self.assertEqual(workbook.manifest["数据开始日期"], "2026-09-01")
        self.assertEqual(workbook.manifest["数据结束日期"], "2026-09-02")

    def test_optional_activity_inputs_map_platform_names_to_numbers(self):
        inputs = [{"活动编号": "KM-MJ-001", "活动名称": "可口可乐满减", "活动类型": "满减", "开始时间": "2026-08-31 00:00:00", "结束时间": "2026-09-17 23:59:59", "活动状态": "已结束"}]
        with tempfile.TemporaryDirectory() as directory:
            workbook = self._convert(Path(directory), inputs)
        numbers = {row["活动编号"] for row in workbook.tables["标准活动核销明细"]}
        self.assertEqual(numbers, {"KM-MJ-001", "满赠优惠"})
        activities = {row["活动编号"]: row for row in workbook.tables["标准活动"]}
        self.assertEqual(activities["KM-MJ-001"]["开始时间"], "2026-08-31 00:00:00")
        self.assertIn("满赠优惠", activities)


class KuaimaRealSampleTests(unittest.TestCase):
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
            activity_inputs=[],
            coupon_inputs=[],
            output_dir=Path(tempfile.mkdtemp()),
        )
        result = convert_kuaima(request)
        workbook = read_standard_workbook(result.workbook_path)
        self.assertGreater(result.counts["标准客户"], 0)
        self.assertGreater(result.counts["标准商品"], 0)
        self.assertGreater(result.counts["标准订单明细"], 0)
        self.assertEqual([row["活动编号"] for row in workbook.tables["标准活动"]], ["可口可乐满减"])
        execution = workbook.tables["标准活动核销明细"]
        self.assertEqual(len(execution), 136)
        self.assertEqual(round(sum(float(row["优惠金额"]) for row in execution), 2), 2040.0)
        self.assertEqual({row["优惠金额"] for row in execution}, {"15"})
        self.assertTrue(result.sources_zip_path.exists())


if __name__ == "__main__":
    unittest.main()
