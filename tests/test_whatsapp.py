# -*- coding: utf-8 -*-
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

POST = "odoo.addons.otm_b2b_fee_tracker.models.whatsapp.requests.post"


def _response(status=200, body=None):
    resp = MagicMock(status_code=status, text=str(body))
    resp.json.return_value = body if body is not None else {"messages": [{"id": "wamid.TEST"}]}
    return resp


@tagged("post_install", "-at_install")
class TestWhatsapp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        icp = cls.env["ir.config_parameter"].sudo()
        for key, value in {
            "wa_enabled": "yes", "wa_phone_number_id": "1234567890", "wa_token": "TOKEN",
            "wa_tpl_upcoming": "fee_reminder", "wa_tpl_overdue": "fee_overdue",
            "wa_tpl_receipt": "fee_receipt", "wa_language": "en", "wa_country_code": "91",
        }.items():
            icp.set_param("otm_b2b_fee_tracker." + key, value)
        cls.user = cls.env["res.users"].create({
            "name": "Fee User W", "login": "fee_user_wa",
            "group_ids": [(4, cls.env.ref("otm_b2b_fee_tracker.group_b2bfee_user").id)],
        })
        env = cls.env(user=cls.user)
        cls.college = env["otm.b2bfee.college"].create({
            "name": "WA College", "contact_person": "Dr. Mary", "email": "wa@example.com",
            "whatsapp_number": "98470 12345"})
        cls.program = cls.env["otm.b2bfee.program"].create({"name": "WA Program"})
        cls.batch = env["otm.b2bfee.batch"].create({
            "college_id": cls.college.id, "program_id": cls.program.id,
            "academic_year": "WA-TEST", "fee_per_student": 15000.0,
            "student_ids": [(0, 0, {"name": "W%d" % i}) for i in range(20)],
            "plan_line_ids": [
                (0, 0, {"name": "Term 1", "due_date": date.today() - timedelta(days=5), "percent": 50}),
                (0, 0, {"name": "Term 2", "due_date": date.today() + timedelta(days=3), "percent": 50}),
            ],
        })
        cls.batch.action_confirm()
        cls.first, cls.second = cls.batch.installment_ids.sorted("due_date")
        cls.WA = cls.env["otm.b2bfee.whatsapp"]

    def _conf(self):
        return self.env["otm.b2bfee.installment"]._notif_conf()

    def _set(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param("otm_b2b_fee_tracker." + key, value)

    def test_01_number_normalisation(self):
        n = self.WA.normalize_number
        self.assertEqual(n("98470 12345"), "919847012345")
        self.assertEqual(n("+91-98470-12345"), "919847012345")
        self.assertEqual(n("098470 12345"), "919847012345")
        self.assertEqual(n("0091 98470 12345"), "919847012345")
        self.assertEqual(n("+971 50 123 4567"), "971501234567")
        self.assertFalse(n("12345"))
        self.assertFalse(n("abc"))
        self.assertFalse(n(False))

    def test_02_overdue_reminder_payload(self):
        with patch(POST, return_value=_response()) as post:
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        self.assertEqual(post.call_count, 1)
        args, kwargs = post.call_args
        self.assertIn("/v21.0/1234567890/messages", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer TOKEN")
        payload = kwargs["json"]
        self.assertEqual(payload["to"], "919847012345")
        self.assertEqual(payload["template"]["name"], "fee_overdue")
        texts = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
        self.assertEqual(len(texts), 6)
        self.assertEqual(texts[0], "Dr. Mary")
        self.assertEqual(texts[1], "Term 1")
        self.assertEqual(texts[4], "5")
        log = self.first.log_ids
        self.assertTrue(log.wa_sent)
        self.assertEqual(log.wa_message_id, "wamid.TEST")
        self.assertTrue(log.email_sent)  # email channel is independent

    def test_03_upcoming_uses_upcoming_template(self):
        with patch(POST, return_value=_response()) as post:
            self.second._process_reminder("before_3", "upcoming", self._conf())
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["template"]["name"], "fee_reminder")
        self.assertEqual(len(payload["template"]["components"][0]["parameters"]), 5)

    def test_04_disabled_makes_no_request(self):
        self._set("wa_enabled", "no")
        with patch(POST) as post:
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        post.assert_not_called()
        self.assertFalse(self.first.log_ids.wa_sent)
        self.assertTrue(self.first.log_ids.email_sent)

    def test_05_missing_number_is_logged(self):
        self.college.write({"whatsapp_number": False, "phone": False})
        with patch(POST) as post:
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        post.assert_not_called()
        self.assertIn("valid WhatsApp number", self.first.log_ids.wa_note)

    def test_06_phone_is_fallback(self):
        self.college.write({"whatsapp_number": False, "phone": "+91 484 200 2002"})
        with patch(POST, return_value=_response()) as post:
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        self.assertEqual(post.call_args.kwargs["json"]["to"], "914842002002")

    def test_07_api_error_does_not_break_email(self):
        err = _response(400, {"error": {"message": "Template name does not exist"}})
        with patch(POST, return_value=err):
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        log = self.first.log_ids
        self.assertFalse(log.wa_sent)
        self.assertIn("Template name does not exist", log.wa_note)
        self.assertTrue(log.email_sent)

    def test_08_network_failure_is_swallowed(self):
        with patch(POST, side_effect=requests.ConnectionError("down")):
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        self.assertFalse(self.first.log_ids.wa_sent)
        self.assertIn("down", self.first.log_ids.wa_note)

    def test_09_missing_template_name(self):
        self._set("wa_tpl_overdue", "")
        with patch(POST) as post:
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        post.assert_not_called()
        self.assertIn("template", self.first.log_ids.wa_note)

    def test_10_receipt_on_posting(self):
        pay = self.env["otm.b2bfee.payment"].with_user(self.user).create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 50000.0})
        with patch(POST, return_value=_response()) as post:
            pay.action_post()
        self.assertEqual(post.call_count, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["template"]["name"], "fee_receipt")
        texts = [p["text"] for p in payload["template"]["components"][0]["parameters"]]
        self.assertIn("50,000", texts[1])
        self.assertEqual(texts[2], pay.name)
        self.assertTrue(any("WhatsApp to 919847012345" in (m.body or "") for m in pay.message_ids))

    def test_11_receipt_failure_never_blocks_posting(self):
        pay = self.env["otm.b2bfee.payment"].with_user(self.user).create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 10000.0})
        with patch(POST, side_effect=requests.Timeout("slow")):
            pay.action_post()
        self.assertEqual(pay.state, "posted")

    def test_12_manual_receipt_needs_a_channel(self):
        pay = self.env["otm.b2bfee.payment"].with_user(self.user).create({
            "college_id": self.college.id, "batch_id": self.batch.id, "amount": 10000.0})
        with patch(POST, return_value=_response()):
            pay.action_post()
        self.college.email = False
        self._set("wa_enabled", "no")
        with self.assertRaises(UserError):
            pay.action_send_receipt()

    def test_13_template_name_validation(self):
        from odoo.exceptions import UserError
        settings = self.env["res.config.settings"].create({
            "b2bfee_wa_tpl_summary": "Internal messages. Summary: {{1}} date"})
        with self.assertRaises(UserError):
            settings.set_values()
        # a stored bad name is reported clearly instead of calling Meta
        self._set("wa_tpl_overdue", "Not A Name {{1}}")
        with patch(POST) as post:
            self.first._process_reminder("overdue_1", "overdue", self._conf())
        post.assert_not_called()
        self.assertIn("Invalid WhatsApp template name", self.first.log_ids.wa_note)

    def test_14_diagnose_reports_phone_and_templates(self):
        self._set("wa_waba_id", "999")

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock(status_code=200)
            if url.endswith("/999/phone_numbers"):
                resp.json.return_value = {"data": [{"id": "OTHER", "display_phone_number": "+1 555"}]}
            elif url.endswith("/999/message_templates"):
                resp.json.return_value = {"data": [{"name": "fee_overdue", "language": "en", "status": "APPROVED"}]}
            else:
                resp.json.return_value = {"display_phone_number": "+91 99999", "verified_name": "Acme"}
            return resp

        with patch("odoo.addons.otm_b2b_fee_tracker.models.whatsapp.requests.get", side_effect=fake_get):
            text = " | ".join(self.env["otm.b2bfee.whatsapp"].diagnose())
        self.assertIn("PROBLEM: phone number 1234567890 is NOT in business account 999", text)
        self.assertIn("fee_overdue [en, APPROVED]", text)
