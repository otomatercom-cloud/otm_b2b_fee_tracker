# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFeeFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Fee User", "login": "fee_user_test",
            "group_ids": [(4, cls.env.ref("otm_b2b_fee_tracker.group_b2bfee_user").id)],
        })
        env = cls.env(user=cls.user)
        cls.college = env["otm.b2bfee.college"].create({"name": "Test College"})
        cls.program = cls.env["otm.b2bfee.program"].create({"name": "Test DipIFR"})
        cls.batch = env["otm.b2bfee.batch"].create({
            "college_id": cls.college.id, "program_id": cls.program.id,
            "academic_year": "2026-27", "fee_per_student": 15000.0,
            "student_ids": [(0, 0, {"name": "S%d" % i}) for i in range(20)],
            "plan_line_ids": [
                (0, 0, {"name": "Term 1", "due_date": date.today() - timedelta(days=5), "percent": 34}),
                (0, 0, {"name": "Term 2", "due_date": date.today() + timedelta(days=60), "percent": 33}),
                (0, 0, {"name": "Term 3", "due_date": date.today() + timedelta(days=150), "percent": 33}),
            ],
        })

    def test_01_confirm_splits_terms(self):
        self.assertEqual(self.batch.total_amount, 300000.0)
        self.batch.action_confirm()
        self.assertEqual(self.batch.state, "running")
        self.assertEqual(
            self.batch.installment_ids.sorted("due_date").mapped("amount"),
            [102000.0, 99000.0, 99000.0])
        self.assertEqual(self.batch.pending, 300000.0)
        self.assertEqual(self.batch.installment_ids.sorted("due_date")[0].state, "overdue")

    def test_02_payment_fifo_and_partial(self):
        self.batch.action_confirm()
        env = self.env(user=self.user)
        pay = env["otm.b2bfee.payment"].create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 110000.0})
        pay.action_post()
        first, second, third = self.batch.installment_ids.sorted("due_date")
        self.assertEqual(first.state, "paid")
        self.assertEqual(second.paid_amount, 8000.0)
        self.assertEqual(second.state, "partial")
        self.assertEqual(self.batch.collected, 110000.0)
        self.assertEqual(self.batch.pending, 190000.0)

    def test_03_overpayment_blocked(self):
        self.batch.action_confirm()
        env = self.env(user=self.user)
        pay = env["otm.b2bfee.payment"].create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 300001.0})
        with self.assertRaises(UserError):
            pay.action_post()

    def test_04_plan_must_total_100(self):
        self.batch.plan_line_ids[0].percent = 30
        with self.assertRaises(UserError):
            self.batch.action_confirm()

    def test_05_cancel_payment_reverts(self):
        self.batch.action_confirm()
        pay = self.env["otm.b2bfee.payment"].create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 50000.0})
        pay.action_post()
        self.assertEqual(self.batch.collected, 50000.0)
        pay.action_cancel()
        self.assertEqual(self.batch.collected, 0.0)

    def test_06_cron_marks_overdue(self):
        self.batch.action_confirm()
        inst = self.batch.installment_ids.sorted("due_date")[1]
        inst.due_date = date.today() - timedelta(days=3)
        self.env["otm.b2bfee.installment"]._cron_refresh_status()
        self.assertEqual(inst.state, "overdue")
        self.assertEqual(inst.days_overdue, 3)
