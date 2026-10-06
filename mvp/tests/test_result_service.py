import sqlite3
import tempfile
import unittest
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
            "模板版本": "v1", "转换工具版本": "v1", "经销商名称": "羿柏", "平台名称": "舟谱",
            "数据开始日期": "2026-08-19", "数据结束日期": "2026-09-08", "生成时间": "2026-09-23 00:00:00",
        },
    )


class ResultServiceTests(unittest.TestCase):
    def test_gift_limit_and_dual_coupon_follow_verified_rules(self):
        workbook = workbook_with_rows(**{
            "标准客户": [{"客户编号": "门店|A", "客户名称": "门店"}],
            "标准商品": [
                {"商品编号": "P1", "商品名称": "雪碧330"},
                {"商品编号": "G1", "商品名称": "(赠品)雪碧抱枕"},
            ],
            "标准订单明细": [
                {"单据编号": "O1", "下单时间": "2026-08-19 10:00:00", "客户编号": "门店|A", "商品编号": "P1", "数量": "10", "优惠前金额": "120", "实付金额": "120", "订单状态": "已完成"},
                {"单据编号": "O1", "下单时间": "2026-08-19 10:00:00", "客户编号": "门店|A", "商品编号": "G1", "数量": "1", "优惠前金额": "0", "实付金额": "0", "订单状态": "已完成"},
                {"单据编号": "O2", "下单时间": "2026-08-20 10:00:00", "客户编号": "门店|A", "商品编号": "P1", "数量": "10", "优惠前金额": "150", "实付金额": "150", "订单状态": "已完成"},
                {"单据编号": "O2", "下单时间": "2026-08-20 10:00:00", "客户编号": "门店|A", "商品编号": "G1", "数量": "1", "优惠前金额": "0", "实付金额": "0", "订单状态": "已完成"},
            ],
            "标准履约": [
                {"单据编号": "O1", "履约订单状态": "已完成", "完成时间": "2026-09-01 00:00:00"},
                {"单据编号": "O2", "履约订单状态": "已完成", "完成时间": "2026-09-01 00:00:00"},
            ],
            "标准活动": [{"活动编号": "ZP-MZ-001", "活动名称": "雪碧系列满100元送抱枕", "活动类型": "满赠", "促销方式": "满一定金额立赠", "开始时间": "2026-08-19 00:00:00", "结束时间": "2026-08-26 23:59:59", "活动状态": "已结束"}],
            "标准活动规则": [{"活动编号": "ZP-MZ-001", "规则编号": "R1", "门槛类型": "金额", "门槛值": "100", "立减金额": "0"}],
            "标准活动权益": [{"活动编号": "ZP-MZ-001", "规则编号": "R1", "权益编号": "B1", "权益类型": "赠品", "赠品商品名称": "(赠品)雪碧抱枕", "赠品数量": "1"}],
            "标准活动范围": [
                {"活动编号": "ZP-MZ-001", "范围编号": "S1", "范围类别": "商品", "范围维度": "商品名称前缀", "范围值": "雪碧"},
                {"活动编号": "ZP-MZ-001", "范围编号": "S2", "范围类别": "限购", "范围维度": "每客户次数", "范围值": "1"},
            ],
            "标准优惠券核销明细": [
                {"优惠券编号": "C1", "客户编号": "门店|A", "状态": "已使用", "订单号": "O1", "优惠金额": "15"},
                {"优惠券编号": "C2", "客户编号": "门店|A", "状态": "已使用", "使用期限": "关联单据:O1,O2", "优惠金额": "15"},
            ],
        })
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "result.db"
            create_database(db_path)
            connection = sqlite3.connect(db_path)
            import_snapshot(connection, workbook, ArchiveMetadata("sources.zip", "hash", 1), calc_date="2026-09-23")
            run = connection.execute("SELECT coupon_benefit, activity_benefit FROM calculation_run").fetchone()
            fee = connection.execute("SELECT gift_qty_entitled, gift_qty_actual, actual_discount_total, settle_status FROM activity_fee_summary").fetchone()
            consistency = {row[0]: row[1:] for row in connection.execute("SELECT h.order_no, e.consistency, e.gift_qty_entitled, e.gift_qty_actual FROM entitlement_check e JOIN order_header h ON h.order_id=e.order_id")}
            release = connection.execute("SELECT SUM(is_candidate) FROM release_candidate").fetchone()[0]
            dual = connection.execute("SELECT COUNT(*) FROM calculation_quality_issue WHERE issue_type='返券双单号无法唯一归因'").fetchone()[0]
        self.assertEqual(run, (15.0, 0.0))
        self.assertEqual(fee[0], 1)
        self.assertEqual(fee[1], 2)
        self.assertEqual(fee[2], 0)
        self.assertEqual(fee[3], "按赠品数量统计(不结算单价)")
        self.assertEqual(consistency["O1"][0], "一致")
        self.assertEqual(consistency["O2"][0], "差异")
        self.assertEqual(release, 2)
        self.assertEqual(dual, 1)


if __name__ == "__main__":
    unittest.main()
