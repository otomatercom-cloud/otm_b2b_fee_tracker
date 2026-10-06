# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class B2bFeeCollegeDashboard(models.AbstractModel):
    _name = "otm.b2bfee.college.dashboard"
    _description = "B2B Fee College Dashboard Data"

    @api.model
    def get_college_data(self, college_id):
        college = self.env["otm.b2bfee.college"].browse(int(college_id)).exists()
        if not college:
            raise UserError(_("This college no longer exists."))
        data = self.env["otm.b2bfee.dashboard"].get_dashboard_data({"college_id": college.id})
        stats = data["colleges"][0] if data["colleges"] else {
            "health": "good", "ontime_pct": None, "avg_delay": None,
            "oldest_overdue_days": 0, "collection_pct": 0.0}
        batches = self.env["otm.b2bfee.batch"].search([("college_id", "=", college.id)])
        payments = self.env["otm.b2bfee.payment"].search(
            [("college_id", "=", college.id), ("state", "!=", "cancel")], limit=15)
        data.update({
            "college": {
                "id": college.id, "name": college.name, "code": college.code or "",
                "city": college.city or "", "contact_person": college.contact_person or "",
                "phone": college.phone or "", "whatsapp": college.whatsapp_number or "",
                "email": college.email or "", "owner": college.owner_id.name or "",
                "mou_date": fields.Date.to_string(college.mou_date) if college.mou_date else "",
            },
            "stats": stats,
            "batches": [{
                "id": b.id, "name": b.name, "program": b.program_id.name,
                "year": b.academic_year, "state": b.state, "students": b.student_count,
                "contract": b.total_amount, "collected": b.collected, "pending": b.pending,
                "payable": b.state == "running",
            } for b in batches],
            "payments": [{
                "id": p.id, "name": p.name, "date": fields.Date.to_string(p.date),
                "batch": p.batch_id.name, "program": p.batch_id.program_id.name,
                "mode": dict(p._fields["payment_mode"].selection).get(p.payment_mode),
                "reference": p.reference or "", "amount": p.amount, "state": p.state,
            } for p in payments],
            "modes": [{"id": k, "label": v} for k, v in
                      self.env["otm.b2bfee.payment"]._fields["payment_mode"].selection],
        })
        return data

    @api.model
    def quick_payment(self, college_id, vals):
        """Create and post a payment in one step (same rules as the payment form)."""
        vals = vals or {}
        try:
            amount = float(vals.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            raise UserError(_("Enter an amount greater than zero."))
        if not vals.get("batch_id"):
            raise UserError(_("Select the batch this payment is for."))
        payment = self.env["otm.b2bfee.payment"].create({
            "college_id": int(college_id), "batch_id": int(vals["batch_id"]),
            "amount": amount, "date": vals.get("date") or fields.Date.context_today(self),
            "payment_mode": vals.get("payment_mode") or "bank",
            "reference": vals.get("reference") or False, "note": vals.get("note") or False,
        })
        payment.action_post()
        return {"id": payment.id, "name": payment.name}
