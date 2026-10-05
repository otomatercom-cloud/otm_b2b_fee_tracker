# -*- coding: utf-8 -*-
from odoo import fields, models


class B2bFeeProgram(models.Model):
    _name = "otm.b2bfee.program"
    _description = "B2B Program"
    _order = "name"

    name = fields.Char(string="Program Name", required=True)
    default_fee = fields.Monetary(string="Default Fee", currency_field="currency_id")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")

    _name_uniq = models.Constraint("unique(name)", "Program name must be unique.")
