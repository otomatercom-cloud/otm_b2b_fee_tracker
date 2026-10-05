# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)


class B2bFeePayment(models.Model):
    _name = "otm.b2bfee.payment"
    _description = "B2B College Payment"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Receipt No.", default="New", readonly=True, copy=False)
    college_id = fields.Many2one(
        "otm.b2bfee.college", string="College", required=True,
        ondelete="restrict", tracking=True)
    batch_id = fields.Many2one(
        "otm.b2bfee.batch", string="Batch", required=True, ondelete="restrict",
        domain="[('college_id', '=', college_id), ('state', '=', 'running')]",
        tracking=True)
    company_id = fields.Many2one(
        related="batch_id.company_id", string="Company", store=True, readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id", string="Currency")
    date = fields.Date(
        string="Payment Date", required=True, default=fields.Date.context_today,
        tracking=True)
    amount = fields.Monetary(
        string="Amount", required=True, currency_field="currency_id", tracking=True)
    payment_mode = fields.Selection(
        [("bank", "Bank Transfer"), ("upi", "UPI"), ("cheque", "Cheque"),
         ("cash", "Cash"), ("other", "Other")],
        string="Mode", default="bank", required=True)
    reference = fields.Char(string="Payment Reference")
    note = fields.Text(string="Notes")
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Proof / Attachments")
    alloc_ids = fields.One2many(
        "otm.b2bfee.payment.alloc", "payment_id", string="Allocations")
    allocated_amount = fields.Monetary(
        string="Manually Allocated", compute="_compute_allocated",
        currency_field="currency_id")
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancel", "Cancelled")],
        string="Status", default="draft", required=True, tracking=True, copy=False)

    _amount_positive = models.Constraint("check(amount > 0)", "Amount must be positive.")

    @api.depends("alloc_ids.amount")
    def _compute_allocated(self):
        for rec in self:
            rec.allocated_amount = sum(rec.alloc_ids.mapped("amount"))

    @api.constrains("college_id", "batch_id")
    def _check_batch_college(self):
        for rec in self:
            if rec.batch_id.college_id != rec.college_id:
                raise ValidationError(_("The batch does not belong to the selected college."))

    @api.onchange("college_id")
    def _onchange_college_id(self):
        if self.batch_id and self.batch_id.college_id != self.college_id:
            self.batch_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("otm.b2bfee.payment") or "New"
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state == "posted" for rec in self):
            raise UserError(_("Posted payments cannot be deleted. Cancel them first."))
        return super().unlink()

    # ------------------------------------------------------------------ actions
    def action_post(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft payments can be posted."))
            batch = rec.batch_id
            if batch.state != "running":
                raise UserError(_("The batch must be Running to receive payments."))
            rounding = rec.currency_id.rounding
            if float_compare(rec.amount, batch.pending, precision_rounding=rounding) > 0:
                raise UserError(_(
                    "Payment %(amount)s exceeds the pending balance %(pending)s of this batch.",
                    amount=rec.amount, pending=batch.pending))
            manual = sum(rec.alloc_ids.mapped("amount"))
            if float_compare(manual, rec.amount, precision_rounding=rounding) > 0:
                raise UserError(_("Manual allocations exceed the payment amount."))
            reserved = {}
            for alloc in rec.alloc_ids:
                inst = alloc.installment_id
                if float_compare(alloc.amount, inst.balance, precision_rounding=rounding) > 0:
                    raise UserError(_(
                        "Allocation to %(term)s exceeds its balance.", term=inst.display_name))
                reserved[inst.id] = reserved.get(inst.id, 0.0) + alloc.amount
            remaining = rec.currency_id.round(rec.amount - manual)
            if not float_is_zero(remaining, precision_rounding=rounding):
                new_allocs = []
                for inst in batch.installment_ids.sorted(lambda i: (i.due_date, i.id)):
                    available = inst.balance - reserved.get(inst.id, 0.0)
                    if float_compare(available, 0.0, precision_rounding=rounding) <= 0:
                        continue
                    take = rec.currency_id.round(min(available, remaining))
                    new_allocs.append({
                        "payment_id": rec.id, "installment_id": inst.id, "amount": take})
                    remaining = rec.currency_id.round(remaining - take)
                    if float_is_zero(remaining, precision_rounding=rounding):
                        break
                if not float_is_zero(remaining, precision_rounding=rounding):
                    raise UserError(_("Could not allocate the full amount to installments."))
                self.env["otm.b2bfee.payment.alloc"].create(new_allocs)
            rec.state = "posted"
            conf = self.env["otm.b2bfee.installment"]._notif_conf()
            if conf["email_receipt"]:
                rec._send_receipt(silent=True)
            wa_conf = self.env["otm.b2bfee.whatsapp"]._conf()
            if wa_conf["enabled"] and wa_conf["receipt"]:
                rec._send_whatsapp_receipt()

    def _send_receipt(self, silent=False):
        """Queue the receipt email (PDF attached by the template). Never blocks posting."""
        self.ensure_one()
        address = self.college_id.email
        if not address:
            if not silent:
                raise UserError(_("The college has no email address."))
            return False
        try:
            with self.env.cr.savepoint():
                template = self.env.ref("otm_b2b_fee_tracker.mail_template_payment_receipt")
                template.send_mail(self.id, force_send=False)
                self.message_post(body=_("Receipt emailed to %s.", address))
        except Exception:
            _logger.exception("Receipt email failed for payment %s", self.id)
            if not silent:
                raise UserError(_("The receipt email could not be queued. See the server log."))
            return False
        return True

    def _send_whatsapp_receipt(self):
        """WhatsApp the receipt summary (text template). Result is noted in the chatter."""
        self.ensure_one()
        college = self.college_id
        wa = self.env["otm.b2bfee.whatsapp"]
        result = wa.send_template(college.whatsapp_number or college.phone, "receipt", [
            college.contact_person or college.name,
            formatLang(self.env, self.amount, currency_obj=self.currency_id),
            self.name, self.batch_id.program_id.name,
            formatLang(self.env, self.batch_id.pending, currency_obj=self.currency_id)])
        if result["sent"]:
            self.message_post(body=_("Receipt sent on WhatsApp to %s.", result["to"]))
        else:
            self.message_post(body=_("WhatsApp receipt not sent: %s", result["note"]))
        return result

    def action_send_receipt(self):
        emailed = whatsapped = 0
        wa_enabled = self.env["otm.b2bfee.whatsapp"]._conf()["enabled"]
        for rec in self:
            if rec.state != "posted":
                raise UserError(_("Only posted payments have a receipt."))
            if rec.college_id.email and rec._send_receipt(silent=True):
                emailed += 1
            if wa_enabled and rec._send_whatsapp_receipt()["sent"]:
                whatsapped += 1
        if not (emailed or whatsapped):
            raise UserError(_(
                "Nothing could be sent. Check the college email / WhatsApp number "
                "and the WhatsApp settings."))
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Receipt"),
                       "message": _("%(e)s email(s) queued, %(w)s WhatsApp message(s) sent.",
                                    e=emailed, w=whatsapped),
                       "type": "success", "sticky": False},
        }

    def action_print_receipt(self):
        self.ensure_one()
        return self.env.ref("otm_b2b_fee_tracker.action_report_payment_receipt").report_action(self)

    def action_cancel(self):
        for rec in self:
            if rec.state == "posted" and not self.env.user.has_group(
                    "otm_b2b_fee_tracker.group_b2bfee_manager"):
                raise UserError(_("Only a Fee Manager can cancel a posted payment."))
            rec.state = "cancel"

    def action_draft(self):
        if not self.env.user.has_group("otm_b2b_fee_tracker.group_b2bfee_manager"):
            raise UserError(_("Only a Fee Manager can reset a payment to draft."))
        self.filtered(lambda r: r.state == "cancel").write({"state": "draft"})


class B2bFeePaymentAlloc(models.Model):
    _name = "otm.b2bfee.payment.alloc"
    _description = "B2B Payment Allocation"
    _order = "id"

    payment_id = fields.Many2one(
        "otm.b2bfee.payment", string="Payment", required=True, ondelete="cascade")
    batch_id = fields.Many2one(
        related="payment_id.batch_id", string="Batch", store=True, readonly=True)
    payment_state = fields.Selection(
        related="payment_id.state", string="Payment Status", store=True, readonly=True)
    currency_id = fields.Many2one(related="payment_id.currency_id", string="Currency")
    installment_id = fields.Many2one(
        "otm.b2bfee.installment", string="Installment", required=True, ondelete="restrict")
    amount = fields.Monetary(
        string="Allocated Amount", required=True, currency_field="currency_id")

    _amount_positive = models.Constraint("check(amount > 0)", "Allocation must be positive.")

    @api.constrains("installment_id", "payment_id")
    def _check_same_batch(self):
        for rec in self:
            if rec.installment_id.batch_id != rec.payment_id.batch_id:
                raise ValidationError(_("Installment must belong to the payment's batch."))
