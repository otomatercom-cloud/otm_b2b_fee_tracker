# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)


class B2bFeeInternalNotify(models.AbstractModel):
    """WhatsApp alerts to the accounts team and directors. Never raises."""
    _name = "otm.b2bfee.internal.notify"
    _description = "B2B Fee Internal WhatsApp Alerts"

    # ------------------------------------------------------------------ helpers
    @api.model
    def _enabled(self):
        return self.env["otm.b2bfee.whatsapp"]._conf()["enabled"]

    @api.model
    def _staff(self, flag):
        return self.env["otm.b2bfee.staff"].sudo().search([(flag, "=", True)])

    @api.model
    def _money(self, amount):
        return formatLang(self.env, amount, currency_obj=self.env.company.currency_id)

    @api.model
    def _deliver(self, staff, kind, params, note_label):
        """Send one template and record the outcome on the recipient."""
        result = self.env["otm.b2bfee.whatsapp"].send_template(
            staff.whatsapp_number, kind, params)
        outcome = _("sent") if result["sent"] else (result["note"] or _("not sent"))
        staff.sudo().write({"last_result": "%s: %s" % (note_label, outcome)[:200]})
        staff.sudo().message_post(body=_("%(label)s – %(outcome)s", label=note_label, outcome=outcome))
        return result

    # ------------------------------------------------------------------ summary
    @api.model
    def _summary_params(self):
        data = self.env["otm.b2bfee.dashboard"].get_dashboard_data({})
        kpis = data["kpis"]
        late = sorted((c for c in data["colleges"] if c["overdue"] > 0),
                      key=lambda c: -c["overdue"])
        top = "; ".join("%s %s (%s d)" % (c["name"], self._money(c["overdue"]),
                                          c["oldest_overdue_days"]) for c in late[:3])
        params = [
            fields.Date.context_today(self).strftime("%d %b %Y"),
            self._money(kpis["collected"]), self._money(kpis["pending"]),
            self._money(kpis["overdue"]), str(len(late)),
            self._money(kpis["due_7"]), top or _("None"),
        ]
        return params, kpis

    @api.model
    def send_summary(self, staff, force=False):
        """Send the summary to one recipient. `force` skips the 'nothing to report' rule."""
        params, kpis = self._summary_params()
        if not force and not (kpis["overdue"] or kpis["due_7"]):
            return {"sent": False, "note": "nothing to report"}
        return self._deliver(staff, "summary", params, _("Summary"))

    @api.model
    def _cron_internal_notifications(self):
        if not self._enabled():
            return
        today = fields.Date.context_today(self)
        for staff in self._staff("daily_digest"):
            if staff.last_daily != today:
                try:
                    with self.env.cr.savepoint():
                        res = self.send_summary(staff)
                        if res.get("sent") or res.get("note") == "nothing to report":
                            staff.sudo().last_daily = today
                except Exception:
                    _logger.exception("Daily team digest failed for %s", staff.id)
        if today.weekday() == 0:  # Monday
            for staff in self._staff("weekly_summary"):
                if staff.last_weekly != today:
                    try:
                        with self.env.cr.savepoint():
                            if self.send_summary(staff, force=True).get("sent"):
                                staff.sudo().last_weekly = today
                    except Exception:
                        _logger.exception("Monday team summary failed for %s", staff.id)

    # ------------------------------------------------------------------ events
    @api.model
    def notify_payment(self, payment):
        if not self._enabled():
            return
        for staff in self._staff("payment_alerts"):
            try:
                with self.env.cr.savepoint():
                    self._deliver(staff, "staff_payment", [
                        payment.college_id.name, self._money(payment.amount),
                        payment.batch_id.program_id.name, payment.name,
                        self._money(payment.batch_id.pending)], _("Payment alert"))
            except Exception:
                _logger.exception("Payment alert failed for %s", staff.id)

    @api.model
    def notify_escalation(self, installment):
        if not self._enabled():
            return
        for staff in self._staff("escalations"):
            try:
                with self.env.cr.savepoint():
                    self._deliver(staff, "staff_escalation", [
                        installment.college_id.name, installment.term_name,
                        installment.program_id.name, str(installment.days_overdue),
                        self._money(installment.balance)], _("Escalation"))
            except Exception:
                _logger.exception("Escalation alert failed for %s", staff.id)
