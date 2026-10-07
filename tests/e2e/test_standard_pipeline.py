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
        # 快马没有独立券订单导出，转换器路径的券费用挂在满减批次；券域理论验收见 test_coupon_matches_audited_baseline。
        self.assertEqual(calculation["coupon_benefit"], 200)
        self.assertEqual((calculation["participating_orders"], calculation["released_orders"]), (136, 133))
        self.assertEqual(calculation["released_activity_benefit"], 1995)
        self.assertEqual((calculation["theoretical_activity_benefit"], calculation["consistent_orders"]), (0, 0))
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


class VerifiedStandardSampleTests(unittest.TestCase):
    """The reviewable sample workbooks must stay the same conversion the e2e baseline used."""

    def test_exported_workbooks_match_verified_counts(self):
        root = ROOT / "docs" / "samples" / "kuaima-verified-standard"
        manjian = read_standard_workbook(root / "满减" / "standard.xlsx")
        manzeng = read_standard_workbook(root / "满赠" / "standard.xlsx")
        coupon = read_standard_workbook(root / "优惠券" / "standard.xlsx")
        self.assertEqual(manjian.manifest["平台名称"], "快马")
        self.assertEqual((manjian.manifest["数据开始日期"], manjian.manifest["数据结束日期"]), ("2026-08-31", "2026-09-17"))
        self.assertEqual(len(manjian.tables["标准活动核销明细"]), 136)
        self.assertEqual(manjian.tables["标准活动"][0]["活动名称"], "可口可乐满减")
        self.assertEqual([row["活动名称"] for row in manjian.tables["标准活动"]], ["可口可乐满减", "test1"])
        self.assertEqual(len(manjian.tables["标准活动规则"]), 2)
        self.assertEqual(next(row["立减金额"] for row in manjian.tables["标准活动规则"] if row["活动编号"] == "KM-COUPON-AUTO-001"), "200")
        self.assertEqual(len(manjian.tables["标准优惠券核销明细"]), 1)
        self.assertEqual(sum(float(row["优惠金额"]) for row in manjian.tables["标准活动核销明细"]), 2040)
        self.assertEqual(len(manzeng.tables["标准活动核销明细"]), 98)
        self.assertEqual(manzeng.tables["标准活动"][0]["活动名称"], "满赠优惠")
        self.assertEqual(len(manzeng.tables["标准优惠券核销明细"]), 0)
        self.assertTrue((root / "ec101_standard库结构与当前数据.xlsx").exists())
        self.assertEqual(manjian.tables["标准活动规则"][0]["门槛值"], "300")
        self.assertEqual(manjian.tables["标准活动规则"][0]["立减金额"], "15")
        self.assertEqual(manjian.tables["标准优惠券配置"][0]["优惠券名称"], "test1")
        self.assertEqual(manjian.tables["标准优惠券配置"][0]["优惠券配置编号"], "KM-COUPON-AUTO-001")
        self.assertEqual(manzeng.tables["标准活动权益"][0]["赠品商品编号"], "348721357")
        self.assertEqual(manzeng.tables["标准活动权益"][0]["赠品单位"], "")
        self.assertEqual([row["优惠券名称"] for row in manjian.tables["标准优惠券配置"]], ["test1"])
        self.assertEqual(manzeng.tables["标准优惠券配置"], [])
        self.assertEqual(len(coupon.tables["标准优惠券核销明细"]), 1)
        self.assertEqual(coupon.tables["标准活动核销明细"], [])
        self.assertEqual(coupon.tables["标准优惠券配置"][0]["优惠券配置编号"], "KM-COUPON-AUTO-001")
        self.assertEqual(sum(float(row["优惠前金额"]) for row in coupon.tables["标准订单明细"]), 1919.8)
        self.assertTrue((root / "优惠券" / "可读.md").exists())
        manzeng_text = (root / "满赠" / "可读.md").read_text(encoding="utf-8")
        self.assertIn("满赠优惠", manzeng_text)
        self.assertIn("348721357", manzeng_text)
        self.assertTrue((root / "原库配置对照" / "对照_可读.md").exists())

    def test_original_config_mapping_does_not_invent_values(self):
        root = ROOT / "docs" / "samples" / "kuaima-verified-standard" / "原库配置对照"
        mapped = read_standard_workbook(root / "原库配置_standard.xlsx")
        names = [row["活动名称"] for row in mapped.tables["标准活动"]]
        self.assertEqual(names, ["可口可乐满减", "满赠优惠", "可口可乐产品288返15元券", "雪碧系列满100元送抱枕", "新客户投放", "test1"])
        rebate = next(row for row in mapped.tables["标准活动权益"] if row["权益类型"] == "返券")
        self.assertEqual(rebate["赠品商品名称"], "")
        self.assertEqual(rebate["赠品数量"], "")
        coupon_nos = [row["优惠券配置编号"] for row in mapped.tables["标准优惠券配置"]]
        self.assertEqual(coupon_nos, ["可口可乐产品288返15元券", "KM-COUPON-MANUAL-001", "KM-COUPON-AUTO-001"])
        self.assertEqual(len(mapped.tables["标准优惠券发放规则"]), 2)
        self.assertTrue((root / "原库配置与标准表对照.xlsx").exists())

    def test_sample_database_snapshot_has_verified_batches(self):
        db_path = ROOT / "docs" / "samples" / "kuaima-verified-standard" / "ec101_standard.db"
        self.assertTrue(db_path.exists(), "找不到验收库快照；应提交 docs/samples/kuaima-verified-standard/ec101_standard.db")
        connection = sqlite3.connect(db_path)
        batches = list(connection.execute("SELECT import_batch_id, coverage_start, coverage_end, status FROM import_batch ORDER BY import_batch_id"))
        runs = list(connection.execute(
            "SELECT import_batch_id, activity_benefit, coupon_benefit, released_activity_benefit, released_coupon_benefit, theoretical_activity_benefit, theoretical_coupon_benefit, consistent_orders, participating_orders, released_orders FROM calculation_run ORDER BY import_batch_id"
        ))
        gift = connection.execute("SELECT SUM(gift_qty_entitled), SUM(gift_qty_actual), SUM(consistency='一致') FROM entitlement_check WHERE calculation_run_id=2").fetchone()
        connection.close()
        self.assertEqual([(row[1], row[2], row[3]) for row in batches], [
            ("2026-08-31", "2026-09-17", "calculated"),
            ("2026-08-19", "2026-08-31", "calculated"),
            ("2026-08-26", "2026-09-08", "calculated"),
            ("2026-08-19", "2026-08-26", "calculated"),
        ])
        self.assertEqual([tuple(row) for row in runs], [
            (1, 2040, 200, 1995, 200, 2040, 200, 136, 136, 133),
            (2, 0, 0, 0, 0, 0, 0, 98, 98, 98),
            (3, 675, 0, 555, 0, 0, 0, 0, 45, 37),
            (4, 0, 0, 0, 0, 0, 0, 0, 142, 142),
        ])
        self.assertEqual(tuple(gift), (98, 98, 98))

    def test_filled_manjian_workbook_recalculates_old_mvp_theoretical(self):
        root = ROOT / "docs" / "samples" / "kuaima-verified-standard"
        workbook = read_standard_workbook(root / "满减" / "standard.xlsx")
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ec101.db"
            create_database(db_path)
            with sqlite3.connect(db_path) as connection:
                imported = import_snapshot(connection, workbook, ArchiveMetadata("sample.xlsx", "sample-满减", 1))
                calculate_batch(connection, imported.import_batch_id, BASELINE_CALC_DATE)
                calculation = run_calculation(connection, imported.import_batch_id)
                consistent = connection.execute("SELECT COUNT(*) FROM entitlement_check WHERE consistency='一致'").fetchone()[0]
                labels = {row[0] for row in connection.execute("SELECT consistency FROM entitlement_check")}
                names = [row[0] for row in connection.execute("SELECT a.activity_name FROM activity_fee_summary s JOIN activity a ON a.activity_id=s.activity_id")]
        self.assertEqual(calculation["activity_benefit"], 2040)
        self.assertEqual(calculation["coupon_benefit"], 200)
        self.assertEqual(calculation["released_activity_benefit"], 1995)
        self.assertEqual(calculation["theoretical_activity_benefit"], 2040)
        self.assertEqual((calculation["participating_orders"], calculation["released_orders"]), (136, 133))
        self.assertEqual(consistent, 136)
        self.assertEqual(labels, {"一致"})
        self.assertEqual(names, ["可口可乐满减"])
        self.assertEqual(calculation["theoretical_coupon_benefit"], 200)

    def test_coupon_matches_audited_baseline(self):
        """券域单独验收：同一张 test1 从满减表抽出后，费用/理论都是 200，且不进活动费用汇总。"""
        root = ROOT / "docs" / "samples" / "kuaima-verified-standard"
        workbook = read_standard_workbook(root / "优惠券" / "standard.xlsx")
        self.assertEqual(len(workbook.tables["标准优惠券核销明细"]), 1)
        self.assertEqual(workbook.tables["标准优惠券核销明细"][0]["优惠金额"], "200")
        self.assertEqual(workbook.tables["标准优惠券核销明细"][0]["订单号"], "1012420526026091000081")
        self.assertEqual(workbook.tables["标准优惠券配置"][0]["优惠券配置编号"], "KM-COUPON-AUTO-001")
        self.assertEqual(workbook.tables["标准活动核销明细"], [])
        self.assertEqual([row["活动编号"] for row in workbook.tables["标准活动"]], ["KM-COUPON-AUTO-001"])
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ec101.db"
            create_database(db_path)
            with sqlite3.connect(db_path) as connection:
                imported = import_snapshot(connection, workbook, ArchiveMetadata("sample.xlsx", "sample-优惠券", 1))
                calculate_batch(connection, imported.import_batch_id, BASELINE_CALC_DATE)
                calculation = run_calculation(connection, imported.import_batch_id)
                check = connection.execute(
                    "SELECT consistency, coupon_benefit, theoretical_coupon_benefit, activity_benefit FROM entitlement_check"
                ).fetchone()
                names = [row[0] for row in connection.execute(
                    "SELECT a.activity_name FROM activity_fee_summary s JOIN activity a ON a.activity_id=s.activity_id"
                )]
                redemption = connection.execute(
                    "SELECT coupon_no, status, discount_amount FROM coupon_redemption"
                ).fetchone()
            overview = query_fee_tpm_overview(db_path, {})
        self.assertEqual(calculation["activity_benefit"], 0)
        self.assertEqual(calculation["coupon_benefit"], 200)
        self.assertEqual(calculation["released_coupon_benefit"], 200)
        self.assertEqual(calculation["theoretical_coupon_benefit"], 200)
        self.assertEqual(calculation["theoretical_activity_benefit"], 0)
        self.assertEqual((calculation["participating_orders"], calculation["released_orders"], calculation["consistent_orders"]), (1, 1, 1))
        self.assertEqual(tuple(check), ("一致", 200, 200, 0))
        self.assertEqual(names, [])
        self.assertEqual(tuple(redemption), ("202609091700313431", "已使用", 200))
        self.assertEqual((overview["releasedCouponBenefit"], overview["submittableAmount"], overview["participatingOrders"]), (200, 0, 1))


if __name__ == "__main__":
    unittest.main()
