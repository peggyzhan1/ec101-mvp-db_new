import json
import tempfile
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from api.server import NotFoundError, import_uploaded_files, make_handler, query_fee_tpm_activities, query_fee_tpm_coupons, query_fee_tpm_issues, query_fee_tpm_overview, query_fee_tpm_roi, query_fee_tpm_settlements
from mvp.import_service import create_database
from mvp.standard_schema import STANDARD_SHEETS
from mvp.standard_workbook import StandardWorkbook, write_standard_workbook


def workbook(directory: Path, name: str, dealer: str, coverage: tuple[str, str], orders: list[dict], activities: list[dict], executions: list[dict], coupons: list[dict] | None = None, coupon_configs: list[dict] | None = None) -> bytes:
    tables = {sheet: [] for sheet in STANDARD_SHEETS[1:]}
    tables.update({
        "标准客户": [{"客户编号": "C1", "客户名称": "客户一"}],
        "标准商品": [{"商品编号": "P1", "商品名称": "可乐"}],
        "标准订单明细": orders,
        "标准活动": activities,
        "标准活动核销明细": executions,
        "标准优惠券配置": coupon_configs or [],
        "标准优惠券核销明细": coupons or [],
    })
    manifest = {"模板版本": "v1", "转换工具版本": "v1", "经销商名称": dealer, "平台名称": "快马", "数据开始日期": coverage[0], "数据结束日期": coverage[1], "生成时间": "2026-09-22 00:00:00"}
    path = directory / f"{name}.xlsx"
    write_standard_workbook(path, StandardWorkbook(tables=tables, manifest=manifest).tables, manifest)
    return path.read_bytes()


def order(order_no: str, time: str, status: str = "已完成") -> dict:
    return {"单据编号": order_no, "下单时间": time, "客户编号": "C1", "客户名称": "客户一", "商品编号": "P1", "数量": "1", "实付金额": "285", "订单状态": status}


class FeeTpmStandardSchemaTests(unittest.TestCase):
    """费用接口按当前批次的最新核算读取 activity_fee_summary / calculation_quality_issue。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.path = root / "ec101_standard.db"
        create_database(self.path)
        manjian = workbook(root, "manjian", "兴路强", ("2026-09-01", "2026-09-17"),
            [order("O1", "2026-09-01 10:00:00"), order("O2", "2026-09-10 10:00:00", "部分发货"), order("O3", "2026-09-21 10:00:00")],
            [{"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "活动类型": "满减"}],
            [{"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "客户编号": "C1", "订单号": o, "优惠金额": "15"} for o in ("O1", "O2", "O3")],
            [{"优惠券编号": "CP1", "客户编号": "C1", "订单号": "O1", "状态": "已使用", "优惠金额": "200"}],
            [{"优惠券配置编号": "KM-COUPON-AUTO-001", "优惠券名称": "test1", "券类型": "单品优惠", "配置状态": "已结束"}])
        manzeng = workbook(root, "manzeng", "兴路强", ("2026-08-19", "2026-08-31"),
            [order("G1", "2026-08-20 10:00:00")],
            [{"活动编号": "满赠优惠", "活动名称": "满赠优惠", "活动类型": "满赠"}],
            [{"活动编号": "满赠优惠", "活动名称": "满赠优惠", "客户编号": "C1", "订单号": "G1", "优惠金额": "0"}])
        self.manjian_run = import_uploaded_files(self.path, manjian, None, "a.zip", calc_date="2026-09-22")["calculation_run_id"]
        self.manzeng_run = import_uploaded_files(self.path, manzeng, None, "b.zip", calc_date="2026-09-22")["calculation_run_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_current_mode_covers_every_current_batch(self):
        payload = query_fee_tpm_activities(self.path, {})
        rows = {row["activityName"]: row for row in payload["rows"]}
        self.assertEqual(payload["mode"], "current")
        self.assertEqual(set(rows), {"可口可乐满减", "满赠优惠"})
        money = rows["可口可乐满减"]
        self.assertEqual((money["benefitKind"], money["actualDiscountTotal"], money["settleAmount"]), ("money", 45, 15))
        self.assertEqual((money["participatingOrders"], money["releasedOrders"], money["pendingOrders"], money["pendingAmount"]), (3, 1, 2, 30))
        self.assertEqual((money["tipCount"], money["status"]), (2, "可提交"))
        gift = rows["满赠优惠"]
        self.assertEqual((gift["benefitKind"], gift["settleAmount"], gift["releasedOrders"], gift["status"]), ("gift", None, 1, "已核验"))

    def test_overview_adds_coupons_and_runs(self):
        overview = query_fee_tpm_overview(self.path, {})
        self.assertEqual(overview["submittableAmount"], 15)
        self.assertEqual((overview["couponBenefit"], overview["releasedCouponBenefit"]), (200, 200))
        self.assertEqual((overview["participatingOrders"], overview["releasedOrders"], overview["giftReleasedOrders"]), (4, 2, 1))
        self.assertEqual({run["calcBatchId"] for run in overview["runs"]}, {self.manjian_run, self.manzeng_run})

    def test_pending_orders_become_tips_attributed_to_their_activity(self):
        issues = query_fee_tpm_issues(self.path, {})["rows"]
        self.assertEqual({issue["orderNo"] for issue in issues}, {"O2", "O3"})
        self.assertTrue(all(issue["level"] == "提示" and issue["activityId"] is not None for issue in issues))

    def test_settlements_only_contain_money_activities_with_released_amount(self):
        rows = query_fee_tpm_settlements(self.path, {})["rows"]
        self.assertEqual([row["activityName"] for row in rows], ["可口可乐满减"])

    def test_pinned_run_and_dealer_filter(self):
        pinned = query_fee_tpm_activities(self.path, {"calc_batch_id": str(self.manzeng_run)})
        self.assertEqual((pinned["mode"], pinned["calcBatchId"], pinned["total"]), ("historical", self.manzeng_run, 1))
        self.assertEqual(query_fee_tpm_activities(self.path, {"dealer": "羿柏"})["total"], 0)
        with self.assertRaises(NotFoundError):
            query_fee_tpm_activities(self.path, {"calc_batch_id": "999"})

    def test_superseded_batch_drops_out_of_current_mode(self):
        root = Path(self.temp.name)
        again = workbook(root, "manjian2", "兴路强", ("2026-09-01", "2026-09-17"), [order("O1", "2026-09-01 10:00:00")],
            [{"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "活动类型": "满减"}],
            [{"活动编号": "可口可乐满减", "活动名称": "可口可乐满减", "客户编号": "C1", "订单号": "O1", "优惠金额": "30"}])
        import_uploaded_files(self.path, again, None, "c.zip", calc_date="2026-09-22")
        rows = {row["activityName"]: row for row in query_fee_tpm_activities(self.path, {})["rows"]}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows["可口可乐满减"]["settleAmount"], 30)
        self.assertEqual(query_fee_tpm_activities(self.path, {"calc_batch_id": str(self.manjian_run)})["rows"][0]["settleAmount"], 15)


class FeeTpmRouteTests(FeeTpmStandardSchemaTests):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.path))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()
        super().tearDown()

    def _get(self, path: str):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_fee_tpm_activity_detail_returns_404_for_an_unknown_activity(self):
        status, payload = self._get("/api/fee-tpm/activities/999")
        self.assertEqual((status, payload["error"]), (404, "not_found"))

    def test_every_page_endpoint_answers_on_the_standard_database(self):
        for path in ("/health", "/api/imports", "/api/fee-tpm/overview", "/api/fee-tpm/activities", "/api/fee-tpm/coupons", "/api/fee-tpm/roi", "/api/fee-tpm/issues", "/api/fee-tpm/settlements",
                     "/api/business-data/orders", "/api/business-data/order-lines", "/api/business-data/activity-executions", "/api/business-data/coupon-redemptions"):
            status, payload = self._get(path)
            self.assertEqual(status, 200, path)
            self.assertNotIn("error", payload, path)
        status, health = self._get("/health")
        self.assertEqual(health["schema_issues"], [])

    def test_activity_verification_report_downloads_xlsx(self):
        activities = query_fee_tpm_activities(self.path, {})["rows"]
        manjian = next(row for row in activities if row["activityName"] == "可口可乐满减")
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("GET", f"/api/fee-tpm/activities/{manjian['activityId']}/verification-report?calc_batch_id={manjian['calcBatchId']}")
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn("spreadsheetml.sheet", response.getheader("Content-Type") or "")
        self.assertTrue(body.startswith(b"PK"))

    def test_coupon_verification_report_downloads_xlsx(self):
        coupons = query_fee_tpm_coupons(self.path, {})["rows"]
        self.assertTrue(coupons)
        coupon = coupons[0]
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("GET", f"/api/fee-tpm/coupons/{coupon['couponConfigId']}/verification-report?calc_batch_id={coupon['calcBatchId']}")
        response = connection.getresponse()
        body = response.read()
        self.assertEqual(response.status, 200)
        self.assertIn("spreadsheetml.sheet", response.getheader("Content-Type") or "")
        self.assertTrue(body.startswith(b"PK"))
        self.assertIn("filename*=UTF-8''", response.getheader("Content-Disposition") or "")

    def test_roi_matches_confirmed_snapshot_formula(self):
        snapshot = Path(__file__).resolve().parents[2] / "docs" / "samples" / "kuaima-verified-standard" / "ec101_standard.db"
        rows = {row["name"]: row for row in query_fee_tpm_roi(snapshot, {})["rows"]}
        self.assertEqual((rows["可口可乐满减"]["cokePaidAmount"], rows["可口可乐满减"]["roi"]), (55021.83, 27.58))
        self.assertIsNone(rows["满赠优惠"]["roi"])
        self.assertEqual(rows["满赠优惠"]["cokePaidAmount"], 23112.68)
        self.assertEqual((rows["test1"]["cokeQtyBase"], rows["test1"]["roi"]), (960, 8.52))
        self.assertEqual(rows["可口可乐产品288返15元券"]["dealer"], "羿柏")
        self.assertEqual(rows["可口可乐产品288返15元券"]["platform"], "舟谱")
        self.assertEqual((rows["可口可乐产品288返15元券"]["feeAmount"], rows["可口可乐产品288返15元券"]["roi"]), (555, 4.3))
        self.assertIsNone(rows["雪碧系列满100元送抱枕"]["roi"])
        self.assertEqual(rows["雪碧系列满100元送抱枕"]["cokePaidAmount"], 44159.5)

    def test_cors_allows_a_browser_preview_origin(self):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("GET", "/api/fee-tpm/overview", headers={"Origin": "https://cursor.com"})
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "https://cursor.com")


if __name__ == "__main__":
    unittest.main()
