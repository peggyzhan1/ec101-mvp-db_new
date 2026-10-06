import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import StandardWorkbook


def workbook_with_rows(**tables):
    all_tables = {sheet: [] for sheet in STANDARD_SHEETS[1:]}
    all_tables.update(tables)
    return StandardWorkbook(
        tables=all_tables,
        manifest={
            "模板版本": "v1", "转换工具版本": "v1", "经销商名称": "测试经销商", "平台名称": "快马",
            "数据开始日期": "2026-08-01", "数据结束日期": "2026-09-30", "生成时间": "2026-09-23 00:00:00",
        },
    )


@contextmanager
def import_workbook(workbook, calc_date="2026-09-23"):
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "actual.db"
        create_database(db_path)
        connection = sqlite3.connect(db_path)
        try:
            import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "hash", 1), calc_date=calc_date)
            yield connection
        finally:
            connection.close()


class ActualResultCalculatorTests(unittest.TestCase):
    def test_discount_execution_sums_actual_and_releases_completed_orders_before_cutoff(self):
        workbook = workbook_with_rows(**{
            "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
            "标准商品": [{"商品编号": "P1", "商品名称": "可乐"}],
            "标准订单明细": [
                {"单据编号": "OK", "下单时间": "2026-09-10 12:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "300", "订单状态": "已完成"},
                {"单据编号": "LATE", "下单时间": "2026-09-22 12:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "300", "订单状态": "已完成"},
                {"单据编号": "OPEN", "下单时间": "2026-09-01 12:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "300", "订单状态": "待签收"},
            ],
            "标准履约": [
                {"单据编号": "OK", "履约订单状态": "已完成"},
                {"单据编号": "LATE", "履约订单状态": "已完成"},
                {"单据编号": "OPEN", "履约订单状态": "待签收"},
            ],
            "标准活动": [{"活动编号": "MJ", "活动名称": "满减", "活动类型": "满减", "促销方式": "立减", "开始时间": "2026-08-01 00:00:00", "结束时间": "2026-09-30 23:59:59", "活动状态": "已结束"}],
            "标准活动核销明细": [
                {"活动编号": "MJ", "订单号": "OK", "优惠金额": "15"},
                {"活动编号": "MJ", "订单号": "LATE", "优惠金额": "15"},
                {"活动编号": "MJ", "订单号": "OPEN", "优惠金额": "15"},
            ],
        })
        with import_workbook(workbook) as connection:
            fee = connection.execute("SELECT actual_discount_total, releasable_discount_total, release_order_count, gift_qty_entitled FROM activity_fee_summary").fetchone()
        self.assertEqual(fee, (45.0, 15.0, 1, None))

    def test_gift_execution_counts_only_orders_in_the_execution_sheet(self):
        workbook = workbook_with_rows(**{
            "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
            "标准商品": [{"商品编号": "P1", "商品名称": "可乐"}, {"商品编号": "G1", "商品名称": "抱枕"}],
            "标准订单明细": [
                {"单据编号": "IN", "下单时间": "2026-08-20 10:00:00", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "100", "订单状态": "已完成"},
                {"单据编号": "IN", "下单时间": "2026-08-20 10:00:00", "客户编号": "C1", "商品编号": "G1", "数量": "1", "实付金额": "0", "订单状态": "已完成"},
                {"单据编号": "OUT", "下单时间": "2026-08-20 11:00:00", "客户编号": "C1", "商品编号": "G1", "数量": "1", "实付金额": "0", "订单状态": "已完成"},
            ],
            "标准活动": [{"活动编号": "MZ", "活动名称": "满赠", "活动类型": "满赠", "促销方式": "立赠", "开始时间": "2026-08-01 00:00:00", "结束时间": "2026-08-31 23:59:59", "活动状态": "已结束"}],
            "标准活动权益": [{"活动编号": "MZ", "规则编号": "R1", "权益编号": "B1", "权益类型": "赠品", "赠品商品名称": "抱枕", "赠品数量": "1"}],
            "标准活动核销明细": [{"活动编号": "MZ", "订单号": "IN", "优惠金额": "0"}],
        })
        with import_workbook(workbook) as connection:
            fee = connection.execute("SELECT gift_qty_actual, releasable_gift_qty, actual_discount_total, settle_status FROM activity_fee_summary").fetchone()
            participants = connection.execute("SELECT COUNT(*) FROM entitlement_check").fetchone()[0]
        self.assertEqual(fee, (1.0, 1.0, 0, "按赠品数量统计(不结算单价)"))
        self.assertEqual(participants, 1)

    def test_empty_execution_gift_uses_window_lines_and_ignores_blank_fulfillment_time(self):
        workbook = workbook_with_rows(**{
            "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
            "标准商品": [{"商品编号": "G1", "商品名称": "抱枕"}, {"商品编号": "UNMATCHED:抱枕", "商品名称": "抱枕"}],
            "标准订单明细": [
                {"单据编号": "DONE", "下单时间": "2026-08-20 10:00:00", "客户编号": "C1", "商品编号": "G1", "数量": "2", "实付金额": "0", "订单状态": "已完成"},
                {"单据编号": "SENT", "下单时间": "2026-08-21 10:00:00", "客户编号": "C1", "商品编号": "UNMATCHED:抱枕", "数量": "1", "实付金额": "0", "订单状态": "已下发"},
                {"单据编号": "EARLY", "下单时间": "2026-08-01 10:00:00", "客户编号": "C1", "商品编号": "G1", "数量": "1", "实付金额": "0", "订单状态": "已完成"},
            ],
            "标准履约": [{"单据编号": "DONE", "履约订单状态": "已完成"}],
            "标准活动": [{"活动编号": "MZ", "活动名称": "满赠", "活动类型": "满赠", "促销方式": "立赠", "开始时间": "2026-08-19 00:00:00", "结束时间": "2026-08-26 23:59:59", "活动状态": "已结束"}],
            "标准活动权益": [{"活动编号": "MZ", "规则编号": "R1", "权益编号": "B1", "权益类型": "赠品", "赠品商品名称": "抱枕", "赠品数量": "1"}],
        })
        with import_workbook(workbook) as connection:
            fee = connection.execute("SELECT gift_qty_actual, releasable_gift_qty, release_order_count FROM activity_fee_summary").fetchone()
            executions = connection.execute("SELECT COUNT(*) FROM activity_execution").fetchone()[0]
        self.assertEqual(fee, (3.0, 2.0, 1))
        self.assertEqual(executions, 0)

    def test_used_coupon_releases_with_completed_order_and_keeps_unlinked_amount(self):
        workbook = workbook_with_rows(**{
            "标准客户": [{"客户编号": "C1", "客户名称": "客户"}],
            "标准商品": [{"商品编号": "P1", "商品名称": "可乐"}],
            "标准订单明细": [
                {"单据编号": "O1", "下单时间": "2026-09-10 16:18:49", "客户编号": "C1", "商品编号": "P1", "数量": "1", "实付金额": "100", "订单状态": "已完成"},
            ],
            "标准履约": [{"单据编号": "O1", "履约订单状态": "已完成"}],
            "标准优惠券配置": [{"优惠券配置编号": "CC1", "优惠券名称": "test1", "配置状态": "有效"}],
            "标准优惠券核销明细": [
                {"优惠券编号": "T1", "客户编号": "C1", "状态": "已使用", "订单号": "O1", "优惠金额": "200"},
                {"优惠券编号": "T2", "客户编号": "C1", "状态": "已使用", "使用期限": "关联单据:O1,O2", "优惠金额": "15"},
                {"优惠券编号": "T3", "客户编号": "C1", "状态": "已领取", "优惠金额": "15"},
            ],
        })
        with import_workbook(workbook) as connection:
            run = connection.execute("SELECT coupon_benefit FROM calculation_run").fetchone()[0]
            fee = connection.execute("SELECT used_count, used_amount, linked_amount, releasable_count, releasable_amount, unlinked_amount FROM coupon_fee_summary").fetchone()
            dual = connection.execute("SELECT reason FROM calculation_quality_issue WHERE issue_type='返券双单号无法唯一归因'").fetchone()[0]
        self.assertEqual(run, 215.0)
        self.assertEqual(fee, (2, 215.0, 200.0, 1, 200.0, 15.0))
        self.assertIn("不能释放", dual)


if __name__ == "__main__":
    unittest.main()
