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
