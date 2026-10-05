# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class B2bFeeBatch(models.Model):
    _name = "otm.b2bfee.batch"
    _description = "B2B Program Batch (Fee Contract)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(
        string="Reference", default="New", readonly=True, copy=False, tracking=True)
    college_id = fields.Many2one(
        "otm.b2bfee.college", string="College", required=True,
        ondelete="restrict", tracking=True)
    program_id = fields.Many2one(
        "otm.b2bfee.program", string="Program", required=True,
        ondelete="restrict", tracking=True)
    academic_year = fields.Char(
        string="Academic Year", required=True, tracking=True, help="e.g. 2026-27")
    fee_per_student = fields.Monetary(
        string="Fee per Student", required=True, currency_field="currency_id", tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("running", "Running"),
         ("closed", "Closed"), ("cancel", "Cancelled")],
        string="Status", default="draft", required=True, tracking=True, copy=False)
    company_id = fields.Many2one(
        related="college_id.company_id", string="Company", store=True, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")
    notes = fields.Text(string="Notes")

    plan_line_ids = fields.One2many("otm.b2bfee.plan.line", "batch_id", string="Payment Terms")
    student_ids = fields.One2many("otm.b2bfee.student", "batch_id", string="Students")
    installment_ids = fields.One2many(
        "otm.b2bfee.installment", "batch_id", string="Installments")

    student_total = fields.Integer(
        string="Number of Students", tracking=True,
        help="Enter the head-count here when you do not track individual students. "
             "If students are entered one by one, their count is used instead.")
    student_count = fields.Integer(
        string="Active Students", compute="_compute_students", store=True)
    total_amount = fields.Monetary(
        string="Contract Value", compute="_compute_students", store=True,
        currency_field="currency_id")
    collected = fields.Monetary(
        string="Collected", compute="_compute_collection", store=True,
        currency_field="currency_id")
    pending = fields.Monetary(
        string="Pending", compute="_compute_collection", store=True,
        currency_field="currency_id")
    plan_percent = fields.Float(string="Plan Total %", compute="_compute_plan_percent")
    collection_pct = fields.Float(string="Collection %", compute="_compute_collection_pct")
    payment_count = fields.Integer(string="Payment Count", compute="_compute_payment_count")

    _batch_uniq = models.Constraint(
        "unique(college_id, program_id, academic_year)",
        "A batch for this college, program and academic year already exists.")
    _students_positive = models.Constraint(
        "check(student_total >= 0)", "Number of students cannot be negative.")
    _fee_positive = models.Constraint(
        "check(fee_per_student >= 0)", "Fee per student cannot be negative.")

    # ------------------------------------------------------------------ computes
    @api.depends("student_ids.state", "student_ids.fee", "student_total", "fee_per_student")
    def _compute_students(self):
        for rec in self:
            active = rec.student_ids.filtered(lambda s: s.state == "active")
            if active:  # students entered one by one: exact fees (with discounts)
                rec.student_count = len(active)
                rec.total_amount = sum(active.mapped("fee"))
            else:  # head-count only
                rec.student_count = rec.student_total
                rec.total_amount = rec.currency_id.round(
                    rec.student_total * rec.fee_per_student) if rec.currency_id \
                    else rec.student_total * rec.fee_per_student

    @api.depends("installment_ids.paid_amount", "installment_ids.balance", "total_amount")
    def _compute_collection(self):
        for rec in self:
            insts = rec.installment_ids
            rec.collected = sum(insts.mapped("paid_amount"))
            rec.pending = sum(insts.mapped("balance")) if insts else rec.total_amount

    @api.depends("plan_line_ids.percent")
    def _compute_plan_percent(self):
        for rec in self:
            rec.plan_percent = sum(rec.plan_line_ids.mapped("percent"))

    @api.depends("collected", "pending")
    def _compute_collection_pct(self):
        for rec in self:
            total = rec.collected + rec.pending
            rec.collection_pct = (rec.collected / total * 100.0) if total else 0.0

    def _compute_payment_count(self):
        Payment = self.env["otm.b2bfee.payment"]
        for rec in self:
            rec.payment_count = Payment.search_count(
                [("batch_id", "=", rec.id), ("state", "=", "posted")]) if rec.id else 0

    # ------------------------------------------------------------------ ORM
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("otm.b2bfee.batch") or "New"
        return super().create(vals_list)

    @api.onchange("program_id")
    def _onchange_program_id(self):
        if self.program_id and not self.fee_per_student:
            self.fee_per_student = self.program_id.default_fee

    # ------------------------------------------------------------------ installments
    def _installment_amounts(self):
        """Return [(plan_line, amount)]; the last term absorbs rounding."""
        self.ensure_one()
        cur = self.currency_id
        lines = self.plan_line_ids.sorted(lambda l: (l.sequence, l.id))
        result, running = [], 0.0
        for idx, line in enumerate(lines):
            if idx == len(lines) - 1:
                amount = cur.round(self.total_amount - running)
            else:
                amount = cur.round(self.total_amount * line.percent / 100.0)
            running += amount
            result.append((line, amount))
        return result

    def _generate_installments(self):
        Installment = self.env["otm.b2bfee.installment"]
        for rec in self:
            Installment.create([{
                "batch_id": rec.id,
                "plan_line_id": line.id,
                "term_name": line.name,
                "sequence": line.sequence,
                "due_date": line.due_date,
                "amount": amount,
            } for line, amount in rec._installment_amounts()])

    # ------------------------------------------------------------------ actions
    def action_confirm(self):
        for rec in self.filtered(lambda r: r.state == "draft"):
            if not rec.plan_line_ids:
                raise UserError(_("Add at least one payment term before confirming."))
            if float_compare(rec.plan_percent, 100.0, precision_digits=2) != 0:
                raise UserError(_(
                    "Payment terms must total 100%% (currently %(p).2f%%).",
                    p=rec.plan_percent))
            if not rec.student_count:
                raise UserError(_("Enter the number of students before confirming."))
            rec._generate_installments()
            rec.state = "running"

    def action_recompute_installments(self):
        """Re-split unpaid installments after student changes."""
        for rec in self.filtered(lambda r: r.state == "running"):
            by_line = {i.plan_line_id.id: i for i in rec.installment_ids}
            for line, amount in rec._installment_amounts():
                inst = by_line.get(line.id)
                if inst and float_is_zero(
                        inst.paid_amount, precision_rounding=rec.currency_id.rounding):
                    inst.amount = amount

    def action_close(self):
        self.filtered(lambda r: r.state == "running").write({"state": "closed"})

    def action_cancel(self):
        Payment = self.env["otm.b2bfee.payment"]
        for rec in self.filtered(lambda r: r.state in ("draft", "running")):
            if Payment.search_count([("batch_id", "=", rec.id), ("state", "=", "posted")]):
                raise UserError(_("Cancel the posted payments of this batch first."))
            rec.state = "cancel"

    def action_view_students(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Students",
            "res_model": "otm.b2bfee.student", "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
            "context": {"default_batch_id": self.id},
        }

    def action_view_installments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Installments",
            "res_model": "otm.b2bfee.installment", "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Payments",
            "res_model": "otm.b2bfee.payment", "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
            "context": {"default_batch_id": self.id,
                        "default_college_id": self.college_id.id},
        }
