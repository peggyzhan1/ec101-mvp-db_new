"""快马-兴路强试点的标准工作簿输入。

活动编号、赠品和核销文件名来自这批试点资料。核算器不读取这些常量。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mvp.scripts.readers import read_table

GIFT_PRODUCT_NO = "348721357"
GIFT_PRODUCT_NAME = "雪碧 冰丝抱枕（赠品勿下）"
COVERAGE_START = "2026-08-19"
COVERAGE_END = "2026-09-17"


def pilot_source_paths(base: Path) -> dict[str, list[Path]]:
    return {
        "customer": [base / "User-202609221722.xlsx"],
        "product": [base / "Product-202609141043.xlsx"],
        "order_detail": [
            base / "满赠" / "快马-兴路强-满赠-订单明细-20260819-20260831.xls",
            base / "满减" / "快马-兴路强-满减-订单明细-20260831-20260917.xls",
            base / "优惠券" / "快马-兴路强-优惠券-test1优惠券-订单明细-20260909-20260912.xls",
        ],
        "activity_execution": [
            base / "满减" / "快马-兴路强-满减-活动明细-20260831-20260917.xls",
            base / "满赠" / "快马-兴路强-满赠-活动明细-20260819-20260831.xls",
        ],
        "coupon_redemption": [
            base / "优惠券" / "快马-兴路强-优惠券-test1优惠券-活动明细-20260909-20260912.xls",
        ],
    }


def pilot_activity_inputs(base: Path) -> list[dict[str, Any]]:
    gift_scopes = [
        {"活动编号": "KM-MZ-001", "范围编号": f"S{index}", "范围类别": "商品", "范围维度": "商品编号", "范围值": product_no}
        for index, product_no in enumerate(_scope_product_nos(base / "满赠" / "满赠指定商品列表.xlsx"), start=1)
    ]
    gift_scopes.extend(
        {"活动编号": "KM-MZ-001", "范围编号": f"C{index}", "范围类别": "客户", "范围维度": "客户类型", "范围值": customer_type}
        for index, customer_type in enumerate(("西乡", "零售", "线下付款客户", "闪电仓", "可口可乐业务"), start=1)
    )
    return [
        {
            "活动编号": "KM-MJ-001",
            "活动名称": "可口可乐满减",
            "活动类型": "满减",
            "促销方式": "满一定金额立减",
            "开始时间": "2026-08-31 10:58:00",
            "结束时间": "2026-09-17 23:59:00",
            "活动状态": "已结束",
            "核销文件": "满减-活动明细",
            "规则": [{"活动编号": "KM-MJ-001", "规则编号": "R1", "门槛类型": "金额", "门槛值": "300", "立减金额": "15", "是否免邮": ""}],
            "权益": [],
            "范围": [
                {"活动编号": "KM-MJ-001", "范围编号": "S1", "范围类别": "商品", "范围维度": "品牌", "范围值": "可口可乐"},
                *({"活动编号": "KM-MJ-001", "范围编号": f"C{index}", "范围类别": "客户", "范围维度": "客户类型", "范围值": customer_type} for index, customer_type in enumerate(("测试类型", "西乡", "零售", "线下付款客户", "闪电仓", "可口可乐业务"), start=1)),
            ],
        },
        {
            "活动编号": "KM-MZ-001",
            "活动名称": "满赠优惠",
            "活动类型": "满赠",
            "促销方式": "满一定金额立赠",
            "开始时间": "2026-08-19 15:15:00",
            "结束时间": "2026-08-31 23:59:00",
            "活动状态": "已结束",
            "核销文件": "满赠-活动明细",
            "规则": [{"活动编号": "KM-MZ-001", "规则编号": "R1", "门槛类型": "金额", "门槛值": "100", "立减金额": "0", "是否免邮": ""}],
            "权益": [{
                "活动编号": "KM-MZ-001", "规则编号": "R1", "权益编号": "B1", "权益类型": "赠品",
                "赠品商品编号": GIFT_PRODUCT_NO, "赠品商品名称": GIFT_PRODUCT_NAME, "赠品数量": "1", "赠品单位": "",
            }],
            "范围": gift_scopes,
        },
    ]


def pilot_coupon_inputs() -> list[dict[str, Any]]:
    return [{
        "优惠券配置编号": "KM-CP-TEST1",
        "优惠券名称": "test1",
        "券类型": "测试券",
        "配置状态": "已结束",
        "发放方式": "定向发放",
        "发放开始时间": "2026-09-09 00:00:00",
        "发放结束时间": "2026-09-12 23:59:59",
        "自动发放时间": "",
        "每次发放数量": "1",
        "每客户领取上限": "1",
        "每日领取上限": "",
        "规则状态": "已结束",
        "有效期类型": "固定期间",
        "使用开始时间": "2026-09-09 00:00:00",
        "使用结束时间": "2026-09-12 23:59:59",
        "领取后有效天数": "",
        "每张券最多使用次数": "1",
        "范围": [{"优惠券配置编号": "KM-CP-TEST1", "范围编号": "S1", "范围类别": "客户", "范围维度": "客户编号", "范围值": "WX-00000000000007507893"}],
    }]


def _scope_product_nos(path: Path) -> list[str]:
    _signature, _sheet, header, rows = read_table(str(path))
    index = header.index("编号")
    return [row[index].strip() for row in rows if index < len(row) and row[index].strip()]
