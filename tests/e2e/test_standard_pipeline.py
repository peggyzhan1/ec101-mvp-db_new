import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.server import get_detail, get_import, get_import_release, query_dataset, query_fee_tpm_overview, query_fee_tpm_settlements
from converters.common import ConversionRequest
from converters.kuaima import convert_kuaima
from desktop_converter.app import build_conversion_request, run_conversion
from mvp.calculation_engine import calculate_batch, run_calculation
from mvp.import_service import ArchiveMetadata, create_database, import_snapshot
from mvp.standard_workbook import read_standard_workbook


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "快马-兴路强-试点"
# 旧 MVP 库（mvp/ec101_mvp.db，核算日 2026-09-22）已对账的兴路强数字，是标准链路的验收基线。
BASELINE_CALC_DATE = "2026-09-22"


class StandardPipelineTests(unittest.TestCase):
    def test_kuaima_source_to_standard_to_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, headers, row):
                path = root / name
                cells = lambda values: "<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>"
                path.write_text("<table>" + cells(headers) + cells(row) + "</table>", encoding="utf-8")
                return path
            customer = write("customer.csv", ["客户编号", "客户名称"], ["C1", "客户1"])
            product = write("product.csv", ["商品编号", "商品名称"], ["P1", "商品1"])
            order = write("order.csv", ["订单编号", "下单时间", "客户编号", "客户名称", "商品编号", "商品名称", "订货数量", "订货金额", "订单状态"], ["O1", "2026-01-01", "C1", "客户1", "P1", "商品1", "2", "20", "已完成"])
            result = convert_kuaima(ConversionRequest("快马", "测试经销商", {"customer": [customer], "product": [product], "order_detail": [order]}, [], [], root / "output"))
            workbook = read_standard_workbook(result.workbook_path)
            db_path = root / "ec101.db"; create_database(db_path)
            with sqlite3.connect(db_path) as connection:
                imported = import_snapshot(connection, workbook, ArchiveMetadata(str(result.sources_zip_path), "hash", result.sources_zip_path.stat().st_size))
                self.assertEqual(imported.status, "imported")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM calculation_run").fetchone()[0], 0)
                calculate_batch(connection, imported.import_batch_id)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM order_header").fetchone()[0], 1)


class KuaimaBaselineRegressionTests(unittest.TestCase):
    """Desktop-tool style requests on the real pilot files must reproduce the audited MVP numbers."""

    def _import(self, root: Path, files: dict[str, list[Path]]):
        request = build_conversion_request("快马", "深圳市兴路强商贸有限公司", files, root / "out")
        result = run_conversion(request)
        workbook = read_standard_workbook(result.workbook_path)
        db_path = root / "ec101.db"
        create_database(db_path)
        with sqlite3.connect(db_path) as connection:
            imported = import_snapshot(connection, workbook, ArchiveMetadata(str(result.sources_zip_path), "hash", 1))
            calculate_batch(connection, imported.import_batch_id, BASELINE_CALC_DATE)
            calculation = run_calculation(connection, imported.import_batch_id)
        return db_path, imported.import_batch_id, calculation

    def test_manjian_matches_audited_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path, batch_id, calculation = self._import(Path(directory), {
                "客户": [PILOT / "User-202609221722.xlsx"],
                "商品": [PILOT / "Product-202609141043.xlsx"],
                "订单": [PILOT / "满减/快马-兴路强-满减-订单明细-20260831-20260917.xls"],
                "活动": [PILOT / "满减/快马-兴路强-满减-活动明细-20260831-20260917.xls"],
                "优惠券": [PILOT / "优惠券/快马-兴路强-优惠券-test1优惠券-活动明细-20260909-20260912.xls"],
            })
            detail = get_import(db_path, batch_id)
            pending = get_import_release(db_path, batch_id, {"candidate": "0"})
        self.assertEqual(calculation["release_cutoff"], "2026-09-20 00:00:00")
        self.assertEqual(calculation["activity_benefit"], 2040)
        self.assertEqual(calculation["coupon_benefit"], 200)
        self.assertEqual((calculation["participating_orders"], calculation["released_orders"]), (136, 133))
        self.assertEqual(calculation["released_activity_benefit"], 1995)
        self.assertEqual(len(detail["activities"]), 1)
        activity = detail["activities"][0]
        self.assertEqual((activity["activity_name"], activity["activity_type"]), ("可口可乐满减", "满减"))
        self.assertEqual((activity["participating_orders"], activity["released_orders"], activity["released_amount"], activity["pending_orders"], activity["pending_amount"]), (136, 133, 1995, 3, 45))
        self.assertEqual(pending["total"], 3)
        self.assertEqual({row["reason"] for row in pending["rows"]}, {"订单状态=部分发货"})

    def test_platform_pages_read_the_same_numbers(self):
        """业务数据页与费用页读到的必须是同一套标准库数字。"""
        with tempfile.TemporaryDirectory() as directory:
            db_path, _, _ = self._import(Path(directory), {
                "客户": [PILOT / "User-202609221722.xlsx"],
                "商品": [PILOT / "Product-202609141043.xlsx"],
                "订单": [PILOT / "满减/快马-兴路强-满减-订单明细-20260831-20260917.xls"],
                "活动": [PILOT / "满减/快马-兴路强-满减-活动明细-20260831-20260917.xls"],
                "优惠券": [PILOT / "优惠券/快马-兴路强-优惠券-test1优惠券-活动明细-20260909-20260912.xls"],
            })
            overview = query_fee_tpm_overview(db_path, {})
            settlements = query_fee_tpm_settlements(db_path, {})["rows"]
            executions = query_dataset(db_path, "activity-executions", {"limit": 1})
            orders = query_dataset(db_path, "orders", {"q": "1012420526026091000081"})
            detail = get_detail(db_path, "orders", str(orders["rows"][0]["id"]))
        self.assertEqual((overview["submittableAmount"], overview["releasedCouponBenefit"], overview["participatingOrders"], overview["releasedOrders"]), (1995, 200, 136, 133))
        self.assertEqual([(row["activityName"], row["settleAmount"], row["releasedOrders"], row["status"]) for row in settlements], [("可口可乐满减", 1995, 133, "可提交")])
        self.assertEqual(executions["total"], 136)
        self.assertEqual((orders["rows"][0]["activities"], orders["rows"][0]["coupons"]), ("可口可乐满减", "202609091700313431"))
        # 订单行优惠 215 = 可乐满减 15 + 券 200；费用只取核销明细里的 15 和 200
        self.assertEqual(orders["rows"][0]["discount_amount"], 215)
        self.assertEqual((detail["release"]["activity_benefit"], detail["release"]["coupon_benefit"], detail["release"]["is_candidate"]), (15, 200, 1))

    def test_manzeng_matches_audited_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path, batch_id, calculation = self._import(Path(directory), {
                "客户": [PILOT / "User-202609221722.xlsx"],
                "商品": [PILOT / "Product-202609141043.xlsx"],
                "订单": [PILOT / "满赠/快马-兴路强-满赠-订单明细-20260819-20260831.xls"],
                "活动": [PILOT / "满赠/快马-兴路强-满赠-活动明细-20260819-20260831.xls"],
            })
            detail = get_import(db_path, batch_id)
        self.assertEqual(calculation["activity_benefit"], 0)
        self.assertEqual((calculation["participating_orders"], calculation["released_orders"]), (98, 98))
        activity = detail["activities"][0]
        self.assertEqual((activity["activity_name"], activity["activity_type"], activity["participating_orders"], activity["released_orders"]), ("满赠优惠", "满赠", 98, 98))


if __name__ == "__main__":
    unittest.main()
