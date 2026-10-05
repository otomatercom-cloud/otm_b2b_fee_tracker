# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2bFeeStudent(models.Model):
    _name = "otm.b2bfee.student"
    _description = "B2B Registered Student"
    _order = "batch_id, name"

    name = fields.Char(string="Student Name", required=True)
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    batch_id = fields.Many2one(
        "otm.b2bfee.batch", string="Batch", required=True, ondelete="cascade")
    college_id = fields.Many2one(
        related="batch_id.college_id", string="College", store=True, readonly=True)
    program_id = fields.Many2one(
        related="batch_id.program_id", string="Program", store=True, readonly=True)
    company_id = fields.Many2one(
        related="batch_id.company_id", string="Company", store=True, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")
    registration_date = fields.Date(
        string="Registered On", default=fields.Date.context_today)
    discount_amount = fields.Monetary(
        string="Discount", currency_field="currency_id", default=0.0)
    fee = fields.Monetary(
        string="Net Fee", compute="_compute_fee", store=True, currency_field="currency_id")
    state = fields.Selection(
        [("active", "Active"), ("dropped", "Dropped")],
        string="Status", default="active", required=True)

    _discount_positive = models.Constraint(
        "check(discount_amount >= 0)", "Discount cannot be negative.")

    @api.depends("batch_id.fee_per_student", "discount_amount")
    def _compute_fee(self):
        for rec in self:
            rec.fee = max(rec.batch_id.fee_per_student - rec.discount_amount, 0.0)
