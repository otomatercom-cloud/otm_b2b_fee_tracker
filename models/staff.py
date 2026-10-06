# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class B2bFeeStaff(models.Model):
    """Internal people (accounts team, directors) who get WhatsApp fee alerts."""
    _name = "otm.b2bfee.staff"
    _description = "B2B Fee Internal WhatsApp Recipient"
    _inherit = ["mail.thread"]
    _order = "role, name"

    name = fields.Char(string="Name", required=True, tracking=True)
    role = fields.Selection(
        [("accounts", "Accounts Team"), ("director", "Director"), ("other", "Other")],
        string="Role", required=True, default="accounts", tracking=True)
    user_id = fields.Many2one("res.users", string="Odoo User")
    whatsapp_number = fields.Char(string="WhatsApp Number", required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company)
    daily_digest = fields.Boolean(
        string="Daily Dues Digest", default=True,
        help="Every morning: overdue and next-7-day dues. Skipped on days with nothing to report.")
    weekly_summary = fields.Boolean(
        string="Monday Summary", default=False,
        help="Every Monday: collected, pending and overdue totals with the top overdue colleges.")
    payment_alerts = fields.Boolean(
        string="Payment Received Alerts", default=False,
        help="A message each time a payment is posted.")
    escalations = fields.Boolean(
        string="Escalations", default=False,
        help="A message when an installment stays overdue past the escalation threshold.")
    last_daily = fields.Date(string="Last Daily Digest", readonly=True, copy=False)
    last_weekly = fields.Date(string="Last Monday Summary", readonly=True, copy=False)
    last_result = fields.Char(string="Last Result", readonly=True, copy=False)

    @api.onchange("user_id")
    def _onchange_user_id(self):
        if self.user_id and not self.name:
            self.name = self.user_id.name

    @api.onchange("role")
    def _onchange_role(self):
        if self.role == "director":
            self.daily_digest, self.weekly_summary = False, True
            self.escalations = True
        elif self.role == "accounts":
            self.daily_digest, self.weekly_summary = True, False
            self.payment_alerts = True

    def action_send_summary_now(self):
        notify = self.env["otm.b2bfee.internal.notify"]
        sent = 0
        for rec in self:
            if notify.send_summary(rec, force=True)["sent"]:
                sent += 1
        if not sent:
            raise UserError(_(
                "Nothing was sent: %s", "; ".join(self.mapped("last_result")) or _("unknown reason")))
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": _("Summary sent to %s person(s).", sent),
                       "type": "success", "sticky": False},
        }
