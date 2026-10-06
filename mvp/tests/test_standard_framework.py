import sqlite3
import unittest

from mvp.standard_framework import calculate_standard_tables, open_calculator_db


def _base() -> dict[str, list[dict[str, str]]]:
    return {
        "标准客户": [{"客户编号": "C1", "客户名称": "客户", "客户类型": "零售"}],
        "标准商品": [{"商品编号": "P1", "商品名称": "可乐", "商品品牌": "可口可乐"}],
        "标准订单明细": [{
            "单据编号": "O1", "下单时间": "2026-08-20 10:00:00", "客户编号": "C1", "商品编号": "P1",
            "商品名称": "可乐", "数量": "2", "订单状态": "已完成",
        }],
        "标准活动": [], "标准活动规则": [], "标准活动权益": [], "标准活动范围": [], "标准活动核销明细": [],
        "标准优惠券配置": [], "标准优惠券发放规则": [], "标准优惠券使用规则": [], "标准优惠券核销明细": [],
    }


class StandardFrameworkTests(unittest.TestCase):
    def test_activity_execution_sheet_is_what_the_framework_calculates(self):
        tables = _base()
        tables["标准活动"].append({"活动编号": "A1", "活动名称": "满减", "活动类型": "满减", "促销方式": "满一定金额立减", "开始时间": "2026-08-01 00:00:00", "结束时间": "2026-08-31 23:59:59", "活动状态": "已结束"})
        tables["标准活动规则"].append({"活动编号": "A1", "规则编号": "R1", "门槛类型": "金额", "门槛值": "100", "立减金额": "10"})
        tables["标准活动核销明细"].append({"活动编号": "A1", "订单号": "O1", "商品总金额": "100", "优惠金额": "10"})
        connection = open_calculator_db()
        prepared, summary = calculate_standard_tables(connection, tables, "经销商", "平台", "2026-09-23")[0]
        self.assertEqual(prepared.order_count, 1)
        self.assertEqual(summary.template, "discount")
        self.assertEqual(str(summary.theoretical_benefit), "10.00")
        self.assertEqual(str(summary.actual_benefit), "10.00")
        connection.close()

    def test_empty_execution_sheet_gives_the_gift_activity_nothing_to_calculate(self):
        tables = _base()
        tables["标准活动"].append({"活动编号": "G1", "活动名称": "送抱枕", "活动类型": "满赠", "促销方式": "满一定金额立赠", "开始时间": "2026-08-19 00:00:00", "结束时间": "2026-08-26 23:59:59", "活动状态": "已结束"})
        tables["标准活动规则"].append({"活动编号": "G1", "规则编号": "R1", "门槛类型": "金额", "门槛值": "100", "立减金额": "0"})
        tables["标准活动权益"].append({"活动编号": "G1", "规则编号": "R1", "权益编号": "B1", "权益类型": "赠品", "赠品商品名称": "(赠品)雪碧抱枕", "赠品数量": "1"})
        tables["标准活动范围"].append({"活动编号": "G1", "范围编号": "S1", "范围类别": "商品", "范围维度": "商品名称前缀", "范围值": "雪碧"})
        connection = open_calculator_db()
        prepared, summary = calculate_standard_tables(connection, tables, "经销商", "平台", "2026-09-23")[0]
        self.assertEqual(prepared.order_count, 0)
        self.assertEqual(summary.template, "gift")
        self.assertEqual(str(summary.gift_qty_entitled), "0.00")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM result_entitlement").fetchone()[0], 0)
        connection.close()

    def test_order_rebate_coupon_uses_the_redemption_amount(self):
        tables = _base()
        tables["标准优惠券配置"].append({"优惠券配置编号": "Q1", "优惠券名称": "返15元券", "券类型": "满返", "配置状态": "已结束"})
        tables["标准优惠券发放规则"].append({"优惠券配置编号": "Q1", "发放方式": "下单返券", "发放开始时间": "2026-08-26 00:00:00", "发放结束时间": "2026-09-08 23:59:59", "每次发放数量": "1", "规则状态": "已结束"})
        tables["标准优惠券使用规则"].append({"优惠券配置编号": "Q1", "券类型": "满返", "有效期类型": "固定期间", "使用开始时间": "2026-08-26 00:00:00", "使用结束时间": "2026-09-08 23:59:59", "每张券最多使用次数": "1", "规则状态": "已结束"})
        tables["标准订单明细"][0]["下单时间"] = "2026-08-27 10:00:00"
        tables["标准优惠券核销明细"].append({"优惠券编号": "C-1", "客户编号": "C1", "状态": "已使用", "订单号": "O1", "优惠金额": "15", "领取时间": "", "使用时间": ""})
        connection = open_calculator_db()
        prepared, summary = calculate_standard_tables(connection, tables, "经销商", "平台", "2026-09-23")[0]
        self.assertEqual(prepared.order_count, 1)
        self.assertEqual(summary.template, "coupon")
        self.assertEqual(str(summary.theoretical_benefit), "15.00")
        self.assertEqual(str(summary.actual_benefit), "15.00")
        self.assertEqual(connection.execute("SELECT issue_mode FROM coupon_issue_rule").fetchone()[0], "order_rebate")
        connection.close()


if __name__ == "__main__":
    unittest.main()
