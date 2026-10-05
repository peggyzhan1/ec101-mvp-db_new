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


if __name__ == "__main__":
    unittest.main()
