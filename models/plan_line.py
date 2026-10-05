# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class B2bFeePlanLine(models.Model):
    _name = "otm.b2bfee.plan.line"
    _description = "B2B Fee Payment Term"
    _order = "sequence, id"

    batch_id = fields.Many2one(
        "otm.b2bfee.batch", string="Batch", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Term", required=True, help="e.g. Term 1")
    due_date = fields.Date(string="Due Date", required=True)
    percent = fields.Float(string="Percent of Fee", required=True, digits=(5, 2))

    _percent_range = models.Constraint(
        "check(percent > 0 and percent <= 100)", "Percent must be between 0 and 100.")

    def _check_editable(self, batches):
        if self.env.su or self.env.user.has_group("otm_b2b_fee_tracker.group_b2bfee_manager"):
            return
        if any(b.state != "draft" for b in batches):
            raise UserError(_("Payment terms can only be changed while the batch is in Draft."))

    @api.model_create_multi
    def create(self, vals_list):
        batches = self.env["otm.b2bfee.batch"].browse(
            [v["batch_id"] for v in vals_list if v.get("batch_id")])
        self._check_editable(batches)
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable(self.batch_id)
        return super().write(vals)

    def unlink(self):
        self._check_editable(self.batch_id)
        return super().unlink()
