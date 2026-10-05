# -*- coding: utf-8 -*-
from collections import defaultdict
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


def _to_int(value):
    """Browser <select> values arrive as strings; never trust the type."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return False


class B2bFeeDashboard(models.AbstractModel):
    _name = "otm.b2bfee.dashboard"
    _description = "B2B Fee Dashboard Data"

    @api.model
    def _scope_domain(self, filters):
        domain = [("batch_id.state", "in", ("running", "closed"))]
        if filters.get("academic_year"):
            domain.append(("batch_id.academic_year", "=", filters["academic_year"]))
        college_id = _to_int(filters.get("college_id"))
        if college_id:
            domain.append(("college_id", "=", college_id))
        program_id = _to_int(filters.get("program_id"))
        if program_id:
            domain.append(("program_id", "=", program_id))
        return domain

    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)
        Installment = self.env["otm.b2bfee.installment"]
        installments = Installment.search(self._scope_domain(filters))
        unpaid = installments.filtered(lambda i: i.balance > 0)
        overdue = unpaid.filtered(lambda i: i.due_date < today)
        batches = installments.batch_id

        def total(recs, field):
            return sum(recs.mapped(field))

        def due_within(days):
            limit = today + relativedelta(days=days)
            return total(unpaid.filtered(lambda i: today <= i.due_date <= limit), "balance")

        contract = total(installments, "amount")
        collected = total(installments, "paid_amount")
        kpis = {
            "contract": contract,
            "collected": collected,
            "pending": total(unpaid, "balance"),
            "overdue": total(overdue, "balance"),
            "overdue_count": len(overdue),
            "collection_pct": round(collected / contract * 100.0, 1) if contract else 0.0,
            "due_7": due_within(7),
            "due_30": due_within(30),
            "colleges": len(installments.college_id),
            "students": sum(batches.filtered(lambda b: b.state == "running").mapped("student_count")),
        }

        # ---- ageing of overdue balances
        buckets = [("1-30 days", 1, 30), ("31-60 days", 31, 60),
                   ("61-90 days", 61, 90), ("90+ days", 91, 10 ** 6)]
        ageing = []
        for label, low, high in buckets:
            recs = overdue.filtered(lambda i: low <= (today - i.due_date).days <= high)
            ageing.append({"label": label, "amount": total(recs, "balance"), "count": len(recs)})

        # ---- payment timeliness per college (from posted allocations)
        allocs = self.env["otm.b2bfee.payment.alloc"].search([
            ("installment_id", "in", installments.ids), ("payment_state", "=", "posted")])
        timing = defaultdict(lambda: {"total": 0.0, "ontime": 0.0, "delay": 0.0})
        for alloc in allocs:
            college = alloc.installment_id.college_id.id
            late = max((alloc.payment_id.date - alloc.installment_id.due_date).days, 0)
            slot = timing[college]
            slot["total"] += alloc.amount
            slot["delay"] += late * alloc.amount
            if late == 0:
                slot["ontime"] += alloc.amount

        # ---- colleges (performance table + top pending chart)
        colleges = []
        for college in installments.college_id:
            recs = installments.filtered(lambda i: i.college_id == college)
            c_contract = total(recs, "amount")
            c_collected = total(recs, "paid_amount")
            c_overdue_recs = recs.filtered(lambda i: i.balance > 0 and i.due_date < today)
            c_overdue = total(c_overdue_recs, "balance")
            oldest = max([(today - i.due_date).days for i in c_overdue_recs], default=0)
            slot = timing.get(college.id)
            ontime_pct = round(slot["ontime"] / slot["total"] * 100.0, 1) if slot and slot["total"] else None
            avg_delay = round(slot["delay"] / slot["total"], 1) if slot and slot["total"] else None
            if c_overdue and (oldest > 30 or (c_contract and c_overdue / c_contract > 0.2)):
                health = "risk"
            elif c_overdue or (ontime_pct is not None and ontime_pct < 70):
                health = "watch"
            else:
                health = "good"
            colleges.append({
                "id": college.id, "name": college.name,
                "contract": c_contract, "collected": c_collected,
                "pending": total(recs.filtered(lambda i: i.balance > 0), "balance"),
                "overdue": c_overdue, "oldest_overdue_days": oldest,
                "collection_pct": round(c_collected / c_contract * 100.0, 1) if c_contract else 0.0,
                "ontime_pct": ontime_pct, "avg_delay": avg_delay, "health": health,
            })
        colleges.sort(key=lambda c: (-c["pending"], c["name"]))

        # ---- by term and by program
        def group(recs, key_fn, label_fn):
            data = {}
            for rec in recs:
                key = key_fn(rec)
                row = data.setdefault(key, {"label": label_fn(rec), "amount": 0.0,
                                            "collected": 0.0, "pending": 0.0, "order": rec.sequence})
                row["amount"] += rec.amount
                row["collected"] += rec.paid_amount
                row["pending"] += rec.balance
            return sorted(data.values(), key=lambda r: (r["order"], r["label"]))

        by_term = group(installments, lambda i: i.term_name, lambda i: i.term_name)
        by_program = group(installments, lambda i: i.program_id.id, lambda i: i.program_id.name)

        # ---- monthly trend: expected (by due month) vs collected (by payment month)
        first_month = today.replace(day=1) - relativedelta(months=11)
        months = [first_month + relativedelta(months=n) for n in range(12)]
        expected = defaultdict(float)
        for inst in installments:
            expected[inst.due_date.replace(day=1)] += inst.amount
        collected_by_month = defaultdict(float)
        payments = self.env["otm.b2bfee.payment"].search([
            ("state", "=", "posted"), ("batch_id", "in", batches.ids),
            ("date", ">=", first_month)])
        for pay in payments:
            collected_by_month[pay.date.replace(day=1)] += pay.amount
        trend = [{"label": m.strftime("%b %y"), "expected": expected.get(m, 0.0),
                  "collected": collected_by_month.get(m, 0.0)} for m in months]

        # ---- 90 day forecast of what is still to come in
        forecast = [{"label": "Overdue", "amount": kpis["overdue"], "overdue": True}]
        for label, low, high in (("0-30 days", 0, 30), ("31-60 days", 31, 60), ("61-90 days", 61, 90)):
            recs = unpaid.filtered(lambda i: low <= (i.due_date - today).days <= high)
            forecast.append({"label": label, "amount": total(recs, "balance"), "overdue": False})

        def line(inst):
            return {
                "id": inst.id, "college": inst.college_id.name, "college_id": inst.college_id.id,
                "term": inst.term_name, "program": inst.program_id.name,
                "due_date": fields.Date.to_string(inst.due_date), "balance": inst.balance,
                "days": (inst.due_date - today).days,
            }

        upcoming = unpaid.filtered(lambda i: 0 <= (i.due_date - today).days <= 30).sorted(
            lambda i: (i.due_date, i.id))[:12]
        top_overdue = overdue.sorted(lambda i: (i.due_date, i.id))[:10]

        all_batches = self.env["otm.b2bfee.batch"].search([("state", "in", ("running", "closed"))])
        currency = self.env.company.currency_id
        return {
            "today": fields.Date.to_string(today),
            "currency": {"symbol": currency.symbol, "position": currency.position,
                         "decimals": currency.decimal_places},
            "kpis": kpis, "ageing": ageing, "colleges": colleges,
            "by_term": by_term, "by_program": by_program, "trend": trend,
            "forecast": forecast,
            "upcoming": [line(i) for i in upcoming],
            "overdue_list": [line(i) for i in top_overdue],
            "options": {
                "years": sorted(set(all_batches.mapped("academic_year")), reverse=True),
                "colleges": [{"id": c.id, "name": c.name} for c in all_batches.college_id.sorted("name")],
                "programs": [{"id": p.id, "name": p.name} for p in all_batches.program_id.sorted("name")],
            },
        }
