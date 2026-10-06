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
    percent = fields.Float(
        string="Percent of Fee", digits=(5, 2),
        help="Only used when no student count is entered on the terms.")
    currency_id = fields.Many2one(related="batch_id.currency_id", string="Currency")
    student_count = fields.Integer(
        string="Students", help="Students paying in this term. Enter it on every term to "
        "calculate each term as students x fee per student.")
    fee_per_student = fields.Monetary(
        string="Fee / Student", currency_field="currency_id",
        compute="_compute_fee_per_student", store=True, readonly=False, precompute=True,
        help="Filled from the batch fee; change it if this term has a different fee.")
    term_amount = fields.Monetary(
        string="Term Amount", currency_field="currency_id",
        compute="_compute_term_amount", store=True)

    _percent_range = models.Constraint(
        "check(percent >= 0 and percent <= 100)", "Percent must be between 0 and 100.")
    _students_range = models.Constraint(
        "check(student_count >= 0)", "Number of students cannot be negative.")

    FLEX_FIELDS = {"student_count", "fee_per_student"}

    @api.depends("batch_id.fee_per_student")
    def _compute_fee_per_student(self):
        for line in self:
            if not line.fee_per_student:
                line.fee_per_student = line.batch_id.fee_per_student

    @api.depends("student_count", "fee_per_student", "currency_id")
    def _compute_term_amount(self):
        for line in self:
            amount = line.student_count * line.fee_per_student
            line.term_amount = line.currency_id.round(amount) if line.currency_id else amount

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
        if set(vals) <= self.FLEX_FIELDS:
            # the head-count of a later term may change while the batch is running
            for line in self:
                if line.batch_id.state in ("closed", "cancel"):
                    raise UserError(_("This batch is closed."))
                if line.batch_id.state == "running" and any(
                        i.paid_amount for i in line.batch_id.installment_ids.filtered(
                            lambda i, l=line: i.plan_line_id == l)):
                    raise UserError(_(
                        "%s already has a payment, so its students and fee cannot change.",
                        line.name))
        else:
            self._check_editable(self.batch_id)
        res = super().write(vals)
        if set(vals) & self.FLEX_FIELDS:
            self.batch_id.filtered(lambda b: b.state == "running").action_recompute_installments()
        return res

    def unlink(self):
        self._check_editable(self.batch_id)
        return super().unlink()
