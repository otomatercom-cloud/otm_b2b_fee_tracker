# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNotifications(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env["res.users"].create({
            "name": "Fee User N", "login": "fee_user_notify",
            "group_ids": [(4, cls.env.ref("otm_b2b_fee_tracker.group_b2bfee_user").id)],
        })
        env = cls.env(user=cls.user)
        cls.college = env["otm.b2bfee.college"].create({
            "name": "Notify College", "email": "college@example.com"})
        cls.program = cls.env["otm.b2bfee.program"].create({"name": "Notify Program"})
        cls.batch = env["otm.b2bfee.batch"].create({
            "college_id": cls.college.id, "program_id": cls.program.id,
            "academic_year": "2026-27", "fee_per_student": 15000.0,
            "student_ids": [(0, 0, {"name": "N%d" % i}) for i in range(20)],
            "plan_line_ids": [
                (0, 0, {"name": "Term 1", "due_date": date.today() - timedelta(days=5), "percent": 34}),
                (0, 0, {"name": "Term 2", "due_date": date.today() + timedelta(days=60), "percent": 33}),
                (0, 0, {"name": "Term 3", "due_date": date.today() + timedelta(days=150), "percent": 33}),
            ],
        })
        cls.batch.action_confirm()
        cls.Installment = cls.env["otm.b2bfee.installment"]
        cls.Log = cls.env["otm.b2bfee.reminder.log"]
        cls.first = cls.batch.installment_ids.sorted("due_date")[0]
        cls.second = cls.batch.installment_ids.sorted("due_date")[1]

    def _mails(self):
        return self.env["mail.mail"].search([("subject", "ilike", "Overdue fee: Term 1")])

    def test_01_overdue_reminder_email_and_task(self):
        before = len(self._mails())
        self.Installment._cron_send_reminders()
        log = self.Log.search([("installment_id", "=", self.first.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.trigger_key, "overdue_1")
        self.assertTrue(log.email_sent)
        self.assertEqual(len(self._mails()), before + 1)
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "otm.b2bfee.batch"), ("res_id", "=", self.batch.id),
            ("user_id", "=", self.user.id)])
        self.assertTrue(activity)
        self.assertFalse(log.escalated)

    def test_02_no_duplicates_on_rerun(self):
        self.Installment._cron_send_reminders()
        self.Installment._cron_send_reminders()
        self.assertEqual(
            self.Log.search_count([("installment_id", "=", self.first.id)]), 1)

    def test_03_escalation_after_threshold(self):
        self.first.due_date = date.today() - timedelta(days=8)
        self.Installment._cron_send_reminders()
        log = self.Log.search([("installment_id", "=", self.first.id)])
        self.assertEqual(log.trigger_key, "overdue_7")
        self.assertTrue(log.escalated)

    def test_04_upcoming_window(self):
        self.second.due_date = date.today() + timedelta(days=3)
        self.Installment._cron_send_reminders()
        log = self.Log.search([("installment_id", "=", self.second.id)])
        self.assertEqual(log.trigger_key, "before_3")
        self.assertEqual(log.kind, "upcoming")

    def test_05_missing_email_is_logged_not_fatal(self):
        self.college.email = False
        self.Installment._cron_send_reminders()
        log = self.Log.search([("installment_id", "=", self.first.id)])
        self.assertFalse(log.email_sent)
        self.assertTrue(log.note)

    def test_06_manual_reminder(self):
        action = self.first.with_user(self.user).action_send_reminder()
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(self.first.reminder_count, 1)

    def test_07_receipt_email_on_post(self):
        pay = self.env["otm.b2bfee.payment"].with_user(self.user).create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 50000.0})
        pay.action_post()
        mails = self.env["mail.mail"].search([("subject", "ilike", pay.name)])
        self.assertEqual(len(mails), 1)
        with self.assertRaises(UserError):
            self.env["otm.b2bfee.payment"].with_user(self.user).create({
                "college_id": self.college.id, "batch_id": self.batch.id,
                "amount": 1.0}).action_send_receipt()
