import unittest

from mvp.standard_schema import STANDARD_SHEETS, SHEET_COLUMNS, validate_rows


class StandardSchemaTests(unittest.TestCase):
    def test_has_reviewed_fixed_sheet_order(self):
        self.assertEqual(
            STANDARD_SHEETS,
            (
                "导入清单", "标准客户", "标准商品", "标准订单明细",
                "标准活动", "标准活动规则", "标准活动权益", "标准活动范围",
                "标准活动核销明细", "标准优惠券配置", "标准优惠券发放规则",
                "标准优惠券使用规则", "标准优惠券适用范围", "标准优惠券核销明细",
                "标准履约",
            ),
        )

    def test_order_detail_contains_reviewed_fields(self):
        self.assertEqual(
            SHEET_COLUMNS["标准订单明细"],
            (
                "单据编号", "下单时间", "客户编号", "客户名称", "商品编号",
                "商品名称", "商品目录", "规格", "商品条码", "单位", "数量",
                "优惠前金额", "活动编号", "优惠券编号", "优惠金额", "实付金额",
                "业务员", "订单来源", "订单类型", "订单状态", "支付方式",
                "下游订单编号", "单价", "退货数量",
            ),
        )

    def test_reviewed_activity_and_coupon_columns(self):
        self.assertEqual(
            SHEET_COLUMNS["标准活动"],
            ("活动编号", "活动名称", "活动类型", "促销方式", "开始时间", "结束时间",
             "是否允许叠加活动", "是否允许叠加优惠券", "活动状态"),
        )
        self.assertEqual(
            SHEET_COLUMNS["标准优惠券核销明细"],
            ("优惠券编号", "客户编号", "客户", "所属业务员", "领取时间", "使用期限",
             "状态", "使用时间", "订单号", "优惠金额"),
        )

    def test_validation_rejects_missing_required_value_and_unknown_column(self):
        issues = validate_rows("标准客户", [{"客户编号": "", "未知字段": "x"}])
        self.assertEqual({issue.code for issue in issues}, {"required", "unknown_column"})


if __name__ == "__main__":
    unittest.main()
