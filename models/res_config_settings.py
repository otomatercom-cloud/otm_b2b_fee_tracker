# -*- coding: utf-8 -*-
from odoo import fields, models

YES_NO = [("yes", "Yes"), ("no", "No")]


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    b2bfee_due_window_days = fields.Integer(
        string="Due-soon Window (days)",
        config_parameter="otm_b2b_fee_tracker.due_window_days", default=7)
    b2bfee_reminder_before = fields.Char(
        string="Reminder Days Before Due",
        config_parameter="otm_b2b_fee_tracker.reminder_before_days", default="7,3")
    b2bfee_overdue_days = fields.Char(
        string="Overdue Reminder Days After Due",
        config_parameter="otm_b2b_fee_tracker.overdue_days", default="1,7,15")
    b2bfee_escalate_from = fields.Integer(
        string="Escalate to Managers After (days overdue)",
        config_parameter="otm_b2b_fee_tracker.escalate_from_days", default=7)
    b2bfee_email_college = fields.Selection(
        YES_NO, string="Email Reminders to College",
        config_parameter="otm_b2b_fee_tracker.email_college", default="yes")
    b2bfee_email_receipt = fields.Selection(
        YES_NO, string="Email Receipt on Posting",
        config_parameter="otm_b2b_fee_tracker.email_receipt", default="yes")

    # ---- WhatsApp (Meta Cloud API)
    b2bfee_wa_enabled = fields.Selection(
        YES_NO, string="Send WhatsApp Reminders",
        config_parameter="otm_b2b_fee_tracker.wa_enabled", default="no")
    b2bfee_wa_receipt = fields.Selection(
        YES_NO, string="WhatsApp Receipt on Posting",
        config_parameter="otm_b2b_fee_tracker.wa_receipt", default="yes")
    b2bfee_wa_phone_number_id = fields.Char(
        string="Phone Number ID", config_parameter="otm_b2b_fee_tracker.wa_phone_number_id")
    b2bfee_wa_token = fields.Char(
        string="Access Token", config_parameter="otm_b2b_fee_tracker.wa_token")
    b2bfee_wa_api_version = fields.Char(
        string="Graph API Version",
        config_parameter="otm_b2b_fee_tracker.wa_api_version", default="v21.0")
    b2bfee_wa_language = fields.Char(
        string="Template Language",
        config_parameter="otm_b2b_fee_tracker.wa_language", default="en")
    b2bfee_wa_country_code = fields.Char(
        string="Default Country Code",
        config_parameter="otm_b2b_fee_tracker.wa_country_code", default="91")
    b2bfee_wa_tpl_upcoming = fields.Char(
        string="Template: Upcoming / Due",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_upcoming")
    b2bfee_wa_tpl_overdue = fields.Char(
        string="Template: Overdue",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_overdue")
    b2bfee_wa_tpl_receipt = fields.Char(
        string="Template: Receipt",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_receipt")
    b2bfee_wa_test_number = fields.Char(string="Test Number")

    def action_b2bfee_wa_test(self):
        """Save the settings, then send the 'upcoming' template to a test number."""
        self.ensure_one()
        self.set_values()
        wa = self.env["otm.b2bfee.whatsapp"]
        result = wa.send_template(
            self.b2bfee_wa_test_number, "upcoming",
            ["Test", "Term 1", "Demo Program", fields.Date.to_string(fields.Date.today()), "1,000.00"])
        message = ("Test message sent to %s." % result["to"]) if result["sent"] \
            else ("Not sent: %s" % result["note"])
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": "WhatsApp test", "message": message,
                       "type": "success" if result["sent"] else "danger", "sticky": not result["sent"]},
        }
