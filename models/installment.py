# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import float_compare

DUE_WINDOW_PARAM = "otm_b2b_fee_tracker.due_window_days"


class B2bFeeInstallment(models.Model):
    _name = "otm.b2bfee.installment"
    _description = "B2B Fee Installment"
    _order = "due_date, id"

    name = fields.Char(string="Installment", compute="_compute_name", store=True)
    batch_id = fields.Many2one(
        "otm.b2bfee.batch", string="Batch", required=True, ondelete="cascade")
    college_id = fields.Many2one(
        related="batch_id.college_id", string="College", store=True, readonly=True)
    program_id = fields.Many2one(
        related="batch_id.program_id", string="Program", store=True, readonly=True)
    company_id = fields.Many2one(
        related="batch_id.company_id", string="Company", store=True, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")
    plan_line_id = fields.Many2one(
        "otm.b2bfee.plan.line", string="Plan Term", ondelete="set null")
    term_name = fields.Char(string="Term", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    due_date = fields.Date(string="Due Date", required=True)
    amount = fields.Monetary(string="Amount", currency_field="currency_id", required=True)
    alloc_ids = fields.One2many(
        "otm.b2bfee.payment.alloc", "installment_id", string="Payment Allocations")
    paid_amount = fields.Monetary(
        string="Paid", compute="_compute_paid", store=True, currency_field="currency_id")
    balance = fields.Monetary(
        string="Balance", compute="_compute_paid", store=True, currency_field="currency_id")
    state = fields.Selection(
        [("upcoming", "Upcoming"), ("due", "Due Soon"), ("partial", "Partially Paid"),
         ("overdue", "Overdue"), ("paid", "Paid")],
        string="Status", compute="_compute_status", store=True)
    days_overdue = fields.Integer(
        string="Days Overdue", compute="_compute_status", store=True)

    _amount_positive = models.Constraint(
        "check(amount >= 0)", "Installment amount cannot be negative.")

    @api.depends("batch_id.name", "term_name")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s - %s" % (rec.batch_id.name or "", rec.term_name or "")

    @api.depends("amount", "alloc_ids.amount", "alloc_ids.payment_state")
    def _compute_paid(self):
        for rec in self:
            paid = sum(rec.alloc_ids.filtered(
                lambda a: a.payment_state == "posted").mapped("amount"))
            rec.paid_amount = paid
            rec.balance = rec.amount - paid

    @api.model
    def _due_window(self):
        return int(self.env["ir.config_parameter"].sudo().get_param(DUE_WINDOW_PARAM, 7))

    def _status_vals(self, today, window):
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        if float_compare(self.balance, 0.0, precision_rounding=rounding) <= 0:
            return {"state": "paid", "days_overdue": 0}
        if self.due_date and self.due_date < today:
            return {"state": "overdue", "days_overdue": (today - self.due_date).days}
        if float_compare(self.paid_amount, 0.0, precision_rounding=rounding) > 0:
            return {"state": "partial", "days_overdue": 0}
        if self.due_date and (self.due_date - today).days <= window:
            return {"state": "due", "days_overdue": 0}
        return {"state": "upcoming", "days_overdue": 0}

    @api.depends("due_date", "balance", "paid_amount")
    def _compute_status(self):
        today = fields.Date.context_today(self)
        window = self._due_window()
        for rec in self:
            vals = rec._status_vals(today, window)
            rec.state = vals["state"]
            rec.days_overdue = vals["days_overdue"]

    @api.model
    def _cron_refresh_status(self):
        """Daily: dates move even when nothing is written, so refresh stored status."""
        today = fields.Date.context_today(self)
        window = self._due_window()
        for rec in self.search([("state", "!=", "paid")]):
            vals = rec._status_vals(today, window)
            if any(rec[key] != val for key, val in vals.items()):
                rec.write(vals)
        return True
