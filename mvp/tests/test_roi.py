import unittest
from pathlib import Path
import sqlite3

from mvp.roi import activity_roi, base_qty, box_factor, coupon_roi, query_roi

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "samples" / "kuaima-verified-standard" / "ec101_standard.db"


class BaseQtyTests(unittest.TestCase):
    def test_box_times_conversion_and_loose_unit_stays(self):
        self.assertEqual(base_qty(20, "箱", "24", 24), 480)
        self.assertEqual(base_qty(2, "件", "12", 12), 24)
        self.assertEqual(base_qty(6, "瓶", "12", 12), 6)
        self.assertEqual(base_qty(3, "罐", None, None), 3)
        self.assertIsNone(base_qty(2, "箱", None, None))
        self.assertEqual(box_factor("1箱=24瓶"), 24)
        self.assertEqual(box_factor("1箱=2包=24瓶"), 24)
        self.assertEqual(base_qty(2, "箱", "1箱=24瓶"), 48)


class SnapshotRoiTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(SNAPSHOT)
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()

    def test_manjian_uses_completed_redemptions_paid_and_base_qty(self):
        row = activity_roi(self.db, 1)
        self.assertEqual(row["name"], "可口可乐满减")
        self.assertEqual(row["completedOrders"], 133)
        self.assertEqual(row["cokeQtyBase"], 24195)
        self.assertEqual(row["cokePaidAmount"], 55021.83)
        self.assertEqual(row["feeAmount"], 1995)
        self.assertEqual(row["roi"], 27.58)

    def test_gift_shows_paid_amount_without_roi(self):
        row = activity_roi(self.db, 3)
        self.assertEqual(row["kind"], "gift")
        self.assertEqual(row["completedOrders"], 98)
        self.assertEqual(row["cokePaidAmount"], 23112.68)
        self.assertEqual(row["cokeQtyBase"], 10068)
        self.assertEqual(row["feeAmount"], 0)
        self.assertIsNone(row["roi"])

    def test_coupon_uses_use_window_and_paid_amount(self):
        row = coupon_roi(self.db, 1)
        self.assertEqual(row["name"], "test1")
        self.assertEqual((row["periodStart"], row["periodEnd"]), ("2026-09-09 16:50:00", "2026-09-12 16:50:00"))
        self.assertEqual(row["completedOrders"], 1)
        self.assertEqual(row["cokeQtyBase"], 960)
        self.assertEqual(row["cokePaidAmount"], 1704.8)
        self.assertEqual(row["feeAmount"], 200)
        self.assertEqual(row["roi"], 8.52)

    def test_query_roi_lists_current_activities_and_coupon(self):
        names = [row["name"] for row in query_roi(SNAPSHOT)]
        self.assertEqual(names, ["可口可乐满减", "满赠优惠", "可口可乐产品288返15元券", "雪碧系列满100元送抱枕", "test1"])

    def test_yibo_rebate_uses_completed_redemptions_and_parsed_box(self):
        row = activity_roi(self.db, 4)
        self.assertEqual(row["name"], "可口可乐产品288返15元券")
        self.assertEqual(row["kind"], "money")
        self.assertEqual(row["completedOrders"], 20)
        self.assertEqual(row["cokeQtyBase"], 942)
        self.assertEqual(row["cokePaidAmount"], 2388.62)
        self.assertEqual(row["feeAmount"], 555)
        self.assertEqual(row["roi"], 4.3)

    def test_yibo_gift_shows_paid_amount_without_roi(self):
        row = activity_roi(self.db, 5)
        self.assertEqual(row["name"], "雪碧系列满100元送抱枕")
        self.assertEqual(row["kind"], "gift")
        self.assertEqual(row["completedOrders"], 130)
        self.assertEqual(row["cokeQtyBase"], 8157)
        self.assertEqual(row["cokePaidAmount"], 44159.5)
        self.assertEqual(row["feeAmount"], 0)
        self.assertIsNone(row["roi"])


if __name__ == "__main__":
    unittest.main()
