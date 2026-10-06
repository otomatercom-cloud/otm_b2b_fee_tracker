# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.service.model import call_kw
from odoo.tests import TransactionCase, tagged


YEAR = "TEST-DASH"  # isolates these tests from demo data


@tagged("post_install", "-at_install")
class TestDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Fee User D", "login": "fee_user_dash",
            "group_ids": [(4, cls.env.ref("otm_b2b_fee_tracker.group_b2bfee_user").id)],
        })
        env = cls.env(user=cls.user)
        cls.program = cls.env["otm.b2bfee.program"].create({"name": "Dash Program"})
        cls.good = env["otm.b2bfee.college"].create({"name": "Good College"})
        cls.late = env["otm.b2bfee.college"].create({"name": "Late College"})
        cls.good_batch = cls._make_batch(env, cls.good, [-40, 30, 90])
        cls.late_batch = cls._make_batch(env, cls.late, [-50, 20, 80])

    @classmethod
    def _make_batch(cls, env, college, offsets):
        batch = env["otm.b2bfee.batch"].create({
            "college_id": college.id, "program_id": cls.program.id,
            "academic_year": YEAR, "fee_per_student": 10000.0,
            "student_ids": [(0, 0, {"name": "%s %d" % (college.name, i)}) for i in range(10)],
            "plan_line_ids": [
                (0, 0, {"name": "Term %d" % (n + 1), "sequence": n,
                        "due_date": date.today() + timedelta(days=off),
                        "percent": 34 if n == 0 else 33})
                for n, off in enumerate(offsets)],
        })
        batch.action_confirm()
        return batch

    def _rpc(self, filters=None):
        # Same dispatch path as the browser's orm.call: args=[], kwargs={...}
        return call_kw(self.env(user=self.user)["otm.b2bfee.dashboard"],
                       "get_dashboard_data", [], {"filters": {"academic_year": YEAR, **(filters or {})}})

    def test_01_rpc_shape_and_totals(self):
        data = self._rpc()
        self.assertEqual(data["kpis"]["contract"], 200000.0)
        self.assertEqual(data["kpis"]["collected"], 0.0)
        self.assertEqual(data["kpis"]["pending"], 200000.0)
        self.assertEqual(data["kpis"]["overdue"], 68000.0)
        self.assertEqual(data["kpis"]["overdue_count"], 2)
        self.assertEqual(len(data["trend"]), 12)
        self.assertEqual(len(data["forecast"]), 4)
        self.assertEqual({c["name"] for c in data["colleges"]}, {"Good College", "Late College"})

    def test_02_ageing_buckets(self):
        ages = {a["label"]: a for a in self._rpc()["ageing"]}
        self.assertEqual(ages["31-60 days"]["count"], 2)
        self.assertEqual(ages["31-60 days"]["amount"], 68000.0)
        self.assertEqual(ages["90+ days"]["count"], 0)

    def test_03_payment_updates_kpis_and_health(self):
        env = self.env(user=self.user)
        pay = env["otm.b2bfee.payment"].create({
            "college_id": self.good.id, "batch_id": self.good_batch.id,
            "amount": 34000.0, "date": date.today() - timedelta(days=39)})
        pay.action_post()  # paid 1 day after its due date (40 days ago)
        data = self._rpc()
        self.assertEqual(data["kpis"]["collected"], 34000.0)
        rows = {c["name"]: c for c in data["colleges"]}
        self.assertEqual(rows["Good College"]["overdue"], 0.0)
        # nothing overdue, but paid late (0% on time) -> Watch, not Good
        self.assertEqual(rows["Good College"]["health"], "watch")
        self.assertEqual(rows["Good College"]["avg_delay"], 1.0)
        self.assertEqual(rows["Good College"]["ontime_pct"], 0.0)
        self.assertEqual(rows["Late College"]["health"], "risk")  # 50 days overdue

    def test_04_filters_accept_string_ids(self):
        # <select>.value from the browser is always a string
        data = self._rpc({"college_id": str(self.late.id), "program_id": str(self.program.id)})
        self.assertEqual(data["kpis"]["contract"], 100000.0)
        self.assertEqual([c["name"] for c in data["colleges"]], ["Late College"])
        self.assertEqual(self._rpc({"college_id": "garbage"})["kpis"]["contract"], 200000.0)

    def test_05_upcoming_and_overdue_lists(self):
        data = self._rpc()
        self.assertEqual(len(data["overdue_list"]), 2)
        # term 2 of both colleges falls inside the 30-day window, soonest first
        self.assertEqual([r["college"] for r in data["upcoming"]], ["Late College", "Good College"])
        self.assertEqual([r["days"] for r in data["upcoming"]], [20, 30])

    def test_06_payment_tracker_matrix(self):
        pay = self.env["otm.b2bfee.payment"].with_user(self.user).create({
            "college_id": self.good.id, "batch_id": self.good_batch.id, "amount": 34000.0})
        pay.action_post()
        part = self.env["otm.b2bfee.payment"].with_user(self.user).create({
            "college_id": self.late.id, "batch_id": self.late_batch.id, "amount": 10000.0})
        part.action_post()
        tracker = {r["college"]: r for r in self._rpc()["tracker"]}
        good, late = tracker["Good College"]["cells"], tracker["Late College"]["cells"]
        self.assertEqual([c["status"] for c in good], ["received", "awaiting", "awaiting"])
        self.assertEqual(good[0]["received_on"], str(date.today()))
        self.assertEqual(good[0]["late_days"], 40)  # due 40 days ago, paid today
        self.assertEqual([c["status"] for c in late], ["partial", "awaiting", "awaiting"])
        self.assertEqual(late[0]["balance"], 24000.0)
        self.assertEqual(tracker["Good College"]["collected"], 34000.0)

    def test_07_college_dashboard_and_quick_payment(self):
        Dash = self.env(user=self.user)["otm.b2bfee.college.dashboard"]
        data = call_kw(Dash, "get_college_data", [self.good.id], {})
        self.assertEqual(data["college"]["name"], "Good College")
        self.assertEqual(len(data["tracker"]), 1)
        self.assertTrue(data["batches"][0]["payable"])
        self.assertIn(data["stats"]["health"], ("good", "watch", "risk"))
        res = call_kw(Dash, "quick_payment", [self.good.id], {"vals": {
            "batch_id": str(self.good_batch.id), "amount": "34000", "payment_mode": "upi",
            "reference": "UTR1"}})
        pay = self.env["otm.b2bfee.payment"].browse(res["id"])
        self.assertEqual((pay.state, pay.payment_mode, pay.amount), ("posted", "upi", 34000.0))
        data = call_kw(Dash, "get_college_data", [self.good.id], {})
        self.assertEqual(data["kpis"]["collected"], 34000.0)
        self.assertEqual(data["payments"][0]["reference"], "UTR1")
        self.assertEqual(data["tracker"][0]["cells"][0]["status"], "received")
        with self.assertRaises(Exception):
            call_kw(Dash, "quick_payment", [self.good.id], {"vals": {"batch_id": self.good_batch.id, "amount": 0}})
        # other college is untouched
        self.assertEqual(call_kw(Dash, "get_college_data", [self.late.id], {})["kpis"]["collected"], 0.0)
        action = self.good.action_open_dashboard()
        self.assertEqual(action["context"]["college_id"], self.good.id)
