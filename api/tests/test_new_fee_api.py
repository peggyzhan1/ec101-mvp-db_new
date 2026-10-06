import sqlite3
import tempfile
import unittest
from pathlib import Path

from api.server import query_fee_tpm_activities, query_fee_tpm_issues, query_fee_tpm_overview, query_fee_tpm_settlements
from mvp.import_service import create_database


class NewFeeApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "standard.db"
        create_database(self.path)
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO import_batch(snapshot_key,dealer_name,platform_name,template_version,converter_version,imported_at,status,is_current) VALUES ('s1','D1','快马','v1','v1','2026-01-01','calculated',1)")
            dealer_id = connection.execute("INSERT INTO dealer_platform(dealer_name,platform_name) VALUES ('D1','快马') RETURNING dealer_platform_id").fetchone()[0]
            activity_id = connection.execute("INSERT INTO activity(import_batch_id,activity_no,activity_name,activity_type,promo_method,start_time,end_time,activity_status) VALUES (1,'A1','满减活动','满减','立减','2026-01-01','2026-01-31','有效') RETURNING activity_id").fetchone()[0]
            calc_id = connection.execute("INSERT INTO calculation_run(import_batch_id,activity_benefit,coupon_benefit,total_benefit,status) VALUES (1,15,10,25,'calculated') RETURNING calculation_run_id").fetchone()[0]
            connection.execute("INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total) VALUES (?,?,15,0)", (calc_id, activity_id))
            connection.execute("INSERT INTO calculation_quality_issue(calculation_run_id,order_no,issue_type,level,reason) VALUES (?,?,?,?,?)", (calc_id, None, "数据检查", "提示", "示例提示"))
            connection.commit()

    def tearDown(self):
        self.directory.cleanup()

    def test_new_schema_fee_queries_use_calculation_run(self):
        rows = query_fee_tpm_activities(self.path, {})["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actualDiscountTotal"], 15)
        self.assertEqual(rows[0]["tpm"], None)
        self.assertEqual(query_fee_tpm_settlements(self.path, {})["total"], 1)
        self.assertEqual(query_fee_tpm_overview(self.path, {})["submittableAmount"], 15)
        self.assertEqual(len(query_fee_tpm_issues(self.path, {})["rows"]), 1)

    def test_actual_results_split_occurred_and_releasable_amounts(self):
        with sqlite3.connect(self.path) as connection:
            calc_id = connection.execute("SELECT calculation_run_id FROM calculation_run").fetchone()[0]
            gift_id = connection.execute("INSERT INTO activity(import_batch_id,activity_no,activity_name,activity_type,promo_method,start_time,end_time,activity_status) VALUES (1,'G1','送抱枕','满赠','立赠','2026-01-01','2026-01-31','有效') RETURNING activity_id").fetchone()[0]
            connection.execute("UPDATE activity_fee_summary SET releasable_discount_total=10, release_order_count=1 WHERE calculation_run_id=?", (calc_id,))
            connection.execute("INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,gift_qty_actual,releasable_discount_total,releasable_gift_qty,release_order_count,settle_status) VALUES (?,?,0,0,111,0,100,100,?)", (calc_id, gift_id, "按赠品数量统计(不结算单价)"))
            config_id = connection.execute("INSERT INTO coupon_config(import_batch_id,config_no,coupon_name,config_status) VALUES (1,'C1','返15元券','有效') RETURNING coupon_config_id").fetchone()[0]
            connection.execute("INSERT INTO coupon_fee_summary(calculation_run_id,coupon_config_id,used_count,used_amount,linked_amount,releasable_count,releasable_amount,unlinked_count,unlinked_amount,settle_status) VALUES (?,?,48,720,675,37,555,3,45,'金额优惠')", (calc_id, config_id))
            connection.commit()
        rows = {row["activityId"]: row for row in query_fee_tpm_activities(self.path, {"limit": 100})["rows"]}
        self.assertEqual(rows[1]["actualDiscountTotal"], 15)
        self.assertEqual(rows[1]["settleAmount"], 10)
        self.assertEqual(rows[gift_id]["giftQtyActual"], 111)
        self.assertEqual(rows[gift_id]["releasableGiftQty"], 100)
        self.assertIsNone(rows[gift_id]["giftQtyEntitled"])
        self.assertIsNone(rows[gift_id]["settleAmount"])
        self.assertEqual(rows[-config_id]["actualDiscountTotal"], 720)
        self.assertEqual(rows[-config_id]["settleAmount"], 555)
        self.assertEqual(rows[-config_id]["releaseCandidates"], 37)
        overview = query_fee_tpm_overview(self.path, {})
        self.assertEqual(overview["submittableAmount"], 565)
        self.assertEqual(overview["giftQtyActual"], 111)
        self.assertEqual(query_fee_tpm_settlements(self.path, {})["total"], 2)

    def test_current_mode_keeps_every_current_batch(self):
        with sqlite3.connect(self.path) as connection:
            latest = connection.execute("INSERT INTO calculation_run(import_batch_id,activity_benefit,coupon_benefit,total_benefit,status) VALUES (1,7,0,7,'calculated') RETURNING calculation_run_id").fetchone()[0]
            connection.execute("INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,releasable_discount_total,gift_cost_total) VALUES (?,?,7,7,0)", (latest, 1))
            connection.execute("INSERT INTO calculation_quality_issue(calculation_run_id,issue_type,level,reason) VALUES (?,?,?,?)", (latest, "T-2释放口径", "提示", "快马"))
            connection.execute("INSERT INTO import_batch(snapshot_key,dealer_name,platform_name,template_version,converter_version,imported_at,status,is_current) VALUES ('s2','D2','舟谱','v1','v1','2026-01-02','calculated',1)")
            connection.execute("INSERT INTO dealer_platform(dealer_name,platform_name) VALUES ('D2','舟谱')")
            gift_id = connection.execute("INSERT INTO activity(import_batch_id,activity_no,activity_name,activity_type,promo_method,start_time,end_time,activity_status) VALUES (2,'G2','舟谱满赠','满赠','立赠','2026-01-01','2026-01-31','有效') RETURNING activity_id").fetchone()[0]
            second = connection.execute("INSERT INTO calculation_run(import_batch_id,activity_benefit,coupon_benefit,total_benefit,status) VALUES (2,0,0,0,'calculated') RETURNING calculation_run_id").fetchone()[0]
            connection.execute("INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,gift_cost_total,gift_qty_actual,releasable_gift_qty,release_order_count,settle_status) VALUES (?,?,0,0,111,100,100,?)", (second, gift_id, "按赠品数量统计(不结算单价)"))
            connection.execute("INSERT INTO calculation_quality_issue(calculation_run_id,issue_type,level,reason) VALUES (?,?,?,?)", (second, "T-2释放口径", "提示", "舟谱"))
            connection.execute("INSERT INTO import_batch(snapshot_key,dealer_name,platform_name,template_version,converter_version,imported_at,status,is_current) VALUES ('s3','D3','其他','v1','v1','2026-01-03','calculated',0)")
            connection.execute("INSERT INTO dealer_platform(dealer_name,platform_name) VALUES ('D3','其他')")
            hidden_activity = connection.execute("INSERT INTO activity(import_batch_id,activity_no,activity_name,activity_type,promo_method,start_time,end_time,activity_status) VALUES (3,'H1','已替换','满减','立减','2026-01-01','2026-01-31','有效') RETURNING activity_id").fetchone()[0]
            hidden = connection.execute("INSERT INTO calculation_run(import_batch_id,activity_benefit,coupon_benefit,total_benefit,status) VALUES (3,999,0,999,'calculated') RETURNING calculation_run_id").fetchone()[0]
            connection.execute("INSERT INTO activity_fee_summary(calculation_run_id,activity_id,actual_discount_total,releasable_discount_total,gift_cost_total) VALUES (?,?,999,999,0)", (hidden, hidden_activity))
            connection.execute("INSERT INTO calculation_quality_issue(calculation_run_id,issue_type,level,reason) VALUES (?,?,?,?)", (hidden, "过期", "警告", "不应出现"))
            connection.commit()
        rows = query_fee_tpm_activities(self.path, {"limit": 100})["rows"]
        amounts = {row["dealer"]: row for row in rows}
        self.assertEqual(set(amounts), {"D1", "D2"})
        self.assertEqual(amounts["D1"]["actualDiscountTotal"], 7)
        self.assertEqual(amounts["D2"]["giftQtyActual"], 111)
        self.assertEqual({row["reason"] for row in query_fee_tpm_issues(self.path, {"limit": 100})["rows"]}, {"快马", "舟谱"})
        historical = query_fee_tpm_activities(self.path, {"calc_batch_id": hidden, "limit": 100})["rows"]
        self.assertEqual([row["activityName"] for row in historical], ["已替换"])
        self.assertEqual(query_fee_tpm_activities(self.path, {"dealer": "D2", "limit": 100})["total"], 1)


if __name__ == "__main__":
    unittest.main()
