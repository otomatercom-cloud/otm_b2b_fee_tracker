# -*- coding: utf-8 -*-
from odoo import api, fields, models


class B2bFeeCollege(models.Model):
    _name = "otm.b2bfee.college"
    _description = "B2B Partner College"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(string="College Name", required=True, tracking=True)
    code = fields.Char(string="Code")
    contact_person = fields.Char(string="Contact Person")
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    city = fields.Char(string="City")
    owner_id = fields.Many2one(
        "res.users", string="Relationship Owner",
        default=lambda self: self.env.user, tracking=True)
    mou_date = fields.Date(string="MoU Date")
    notes = fields.Text(string="Notes")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")

    batch_ids = fields.One2many("otm.b2bfee.batch", "college_id", string="Program Batches")
    batch_count = fields.Integer(string="Batch Count", compute="_compute_totals")
    contract_value = fields.Monetary(
        string="Contract Value", compute="_compute_totals", currency_field="currency_id")
    collected = fields.Monetary(
        string="Collected", compute="_compute_totals", currency_field="currency_id")
    pending = fields.Monetary(
        string="Pending", compute="_compute_totals", currency_field="currency_id")

    _name_uniq = models.Constraint(
        "unique(name, company_id)", "College name must be unique per company.")

    @api.depends("batch_ids.state", "batch_ids.total_amount",
                 "batch_ids.collected", "batch_ids.pending")
    def _compute_totals(self):
        for rec in self:
            batches = rec.batch_ids.filtered(lambda b: b.state != "cancel")
            rec.batch_count = len(batches)
            rec.contract_value = sum(batches.mapped("total_amount"))
            rec.collected = sum(batches.mapped("collected"))
            rec.pending = sum(batches.mapped("pending"))

    def action_view_batches(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Batches",
            "res_model": "otm.b2bfee.batch",
            "view_mode": "list,form",
            "domain": [("college_id", "=", self.id)],
            "context": {"default_college_id": self.id},
        }
