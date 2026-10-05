# -*- coding: utf-8 -*-
from odoo import fields, models


class B2bFeeReminderLog(models.Model):
    _name = "otm.b2bfee.reminder.log"
    _description = "B2B Fee Reminder Log"
    _order = "sent_on desc, id desc"

    installment_id = fields.Many2one(
        "otm.b2bfee.installment", string="Installment", required=True, ondelete="cascade")
    batch_id = fields.Many2one(
        related="installment_id.batch_id", string="Batch", store=True, readonly=True)
    college_id = fields.Many2one(
        related="installment_id.college_id", string="College", store=True, readonly=True)
    company_id = fields.Many2one(
        related="installment_id.company_id", string="Company", store=True, readonly=True)
    trigger_key = fields.Char(string="Trigger", required=True, index=True)
    kind = fields.Selection(
        [("upcoming", "Upcoming / Due"), ("overdue", "Overdue"), ("manual", "Manual")],
        string="Type", required=True)
    sent_on = fields.Datetime(string="Sent On", default=fields.Datetime.now, required=True)
    email_sent = fields.Boolean(string="Email Queued")
    email_to = fields.Char(string="Email To")
    activity_created = fields.Boolean(string="Owner Task Created")
    escalated = fields.Boolean(string="Escalated to Managers")
    note = fields.Char(string="Note")

    _trigger_uniq = models.Constraint(
        "unique(installment_id, trigger_key)",
        "This reminder has already been logged for the installment.")
