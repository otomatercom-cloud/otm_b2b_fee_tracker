# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

POST = "odoo.addons.otm_b2b_fee_tracker.models.whatsapp.requests.post"


def _ok():
    resp = MagicMock(status_code=200, text="ok")
    resp.json.return_value = {"messages": [{"id": "wamid.T"}]}
    return resp


@tagged("post_install", "-at_install")
class TestTeamAlerts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env["ir.config_parameter"].sudo()
        for key, value in {
            "wa_enabled": "yes", "wa_phone_number_id": "111", "wa_token": "T",
            "wa_tpl_summary": "team_summary", "wa_tpl_staff_payment": "team_payment",
            "wa_tpl_staff_escalation": "team_escalation", "wa_tpl_receipt": "r",
            "wa_tpl_overdue": "o", "wa_tpl_upcoming": "u", "escalate_from_days": "3",
        }.items():
            icp.set_param("otm_b2b_fee_tracker." + key, value)
        Staff = cls.env["otm.b2bfee.staff"]
        Staff.search([]).unlink()
        cls.acc = Staff.create({"name": "Anu", "role": "accounts", "whatsapp_number": "98470 11111",
                                "daily_digest": True, "payment_alerts": True})
        cls.dire = Staff.create({"name": "Director", "role": "director", "whatsapp_number": "98470 22222",
                                 "daily_digest": False, "weekly_summary": True, "escalations": True})
        college = cls.env["otm.b2bfee.college"].create({"name": "Team College", "email": False})
        program = cls.env["otm.b2bfee.program"].create({"name": "Team Program"})
        cls.batch = cls.env["otm.b2bfee.batch"].create({
            "college_id": college.id, "program_id": program.id, "academic_year": "TEAM-1",
            "fee_per_student": 10000.0, "student_total": 10,
            "plan_line_ids": [
                (0, 0, {"name": "Term 1", "due_date": date.today() - timedelta(days=10), "percent": 50}),
                (0, 0, {"name": "Term 2", "due_date": date.today() + timedelta(days=3), "percent": 50})]})
        cls.batch.action_confirm()
        cls.college = college

    def _numbers(self, post):
        return [c.kwargs["json"]["to"] for c in post.call_args_list]

    def _templates(self, post):
        return [c.kwargs["json"]["template"]["name"] for c in post.call_args_list]

    def test_01_daily_digest_only_to_digest_recipients_once_a_day(self):
        with patch(POST, return_value=_ok()) as post:
            self.env["otm.b2bfee.internal.notify"]._cron_internal_notifications()
            self.env["otm.b2bfee.internal.notify"]._cron_internal_notifications()  # rerun: no duplicate
        self.assertEqual(self._numbers(post).count("919847011111"), 1)
        self.assertNotIn("919847022222", self._numbers(post))
        self.assertEqual(self.acc.last_daily, date.today())
        params = [p["text"] for p in post.call_args.kwargs["json"]["template"]["components"][0]["parameters"]]
        self.assertEqual(len(params), 7)
        self.assertIn("Team College", params[6])

    def test_02_weekly_summary_goes_to_directors_on_monday(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        with patch(POST, return_value=_ok()) as post, \
                patch("odoo.fields.Date.context_today", return_value=monday):
            self.env["otm.b2bfee.internal.notify"]._cron_internal_notifications()
        self.assertIn("919847022222", self._numbers(post))

    def test_03_payment_alert(self):
        pay = self.env["otm.b2bfee.payment"].create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 20000.0})
        with patch(POST, return_value=_ok()) as post:
            pay.action_post()
        sent = list(zip(self._numbers(post), self._templates(post)))
        self.assertIn(("919847011111", "team_payment"), sent)
        self.assertNotIn("919847022222", [n for n, t in sent])  # directors did not opt in

    def test_04_escalation_alert_to_directors(self):
        first = self.batch.installment_ids.sorted("due_date")[0]
        conf = self.env["otm.b2bfee.installment"]._notif_conf()
        with patch(POST, return_value=_ok()) as post:
            first._process_reminder("overdue_9", "overdue", conf)
        sent = list(zip(self._numbers(post), self._templates(post)))
        self.assertIn(("919847022222", "team_escalation"), sent)

    def test_05_disabled_and_failures_are_silent(self):
        self.env["ir.config_parameter"].sudo().set_param("otm_b2b_fee_tracker.wa_enabled", "no")
        with patch(POST) as post:
            self.env["otm.b2bfee.internal.notify"]._cron_internal_notifications()
        post.assert_not_called()
        self.env["ir.config_parameter"].sudo().set_param("otm_b2b_fee_tracker.wa_enabled", "yes")
        bad = MagicMock(status_code=400, text="x")
        bad.json.return_value = {"error": {"message": "Template does not exist"}}
        with patch(POST, return_value=bad):
            res = self.env["otm.b2bfee.internal.notify"].send_summary(self.acc, force=True)
        self.assertFalse(res["sent"])
        self.assertIn("Template does not exist", self.acc.last_result)

    def test_06_send_summary_now_button(self):
        with patch(POST, return_value=_ok()) as post:
            action = self.dire.action_send_summary_now()
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(self._numbers(post), ["919847022222"])
