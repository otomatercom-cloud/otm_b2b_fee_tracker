# -*- coding: utf-8 -*-
import logging
import re

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, formatLang

_logger = logging.getLogger(__name__)

PARAM = "otm_b2b_fee_tracker."
TPL_UPCOMING = "otm_b2b_fee_tracker.mail_template_reminder_upcoming"
TPL_OVERDUE = "otm_b2b_fee_tracker.mail_template_reminder_overdue"


class B2bFeeInstallmentNotify(models.Model):
    _inherit = "otm.b2bfee.installment"

    log_ids = fields.One2many(
        "otm.b2bfee.reminder.log", "installment_id", string="Reminder History")
    reminder_count = fields.Integer(string="Reminders Sent", compute="_compute_reminders")
    last_reminder_on = fields.Datetime(string="Last Reminder", compute="_compute_reminders")

    @api.depends("log_ids.sent_on")
    def _compute_reminders(self):
        for rec in self:
            rec.reminder_count = len(rec.log_ids)
            rec.last_reminder_on = max(rec.log_ids.mapped("sent_on"), default=False)

    # ------------------------------------------------------------------ config
    @api.model
    def _notif_conf(self):
        icp = self.env["ir.config_parameter"].sudo()

        def ints(key, default):
            raw = icp.get_param(PARAM + key) or default
            vals = {int(x) for x in re.split(r"[,\s]+", raw) if x.strip().isdigit()}
            return sorted(vals)

        def flag(key):
            return icp.get_param(PARAM + key, "yes") != "no"

        return {
            "before": ints("reminder_before_days", "7,3"),
            "overdue": ints("overdue_days", "1,7,15"),
            "escalate_from": int(icp.get_param(PARAM + "escalate_from_days") or 7),
            "email_college": flag("email_college"),
            "email_receipt": flag("email_receipt"),
            "wa_enabled": icp.get_param(PARAM + "wa_enabled", "no") == "yes",
        }

    # ------------------------------------------------------------------ helpers
    def _reminder_trigger(self, today, conf):
        """Return (key, kind) for the reminder due today, or None."""
        self.ensure_one()
        delta = (self.due_date - today).days
        if delta == 0:
            return "due_today", "upcoming"
        if delta > 0:
            for days in conf["before"]:
                if days and delta <= days:
                    return "before_%d" % days, "upcoming"
            return None
        late = -delta
        hits = [d for d in conf["overdue"] if d and late >= d]
        return ("overdue_%d" % max(hits), "overdue") if hits else None

    def _owner_user(self):
        self.ensure_one()
        return self.college_id.owner_id

    def _manager_users(self):
        group = self.env.ref("otm_b2b_fee_tracker.group_b2bfee_manager")
        return group.sudo().user_ids.filtered(
            lambda u: u.active and u.id != SUPERUSER_ID and not u.share)

    def _queue_reminder_email(self, kind):
        """Queue the college email. Returns (queued, address, note)."""
        self.ensure_one()
        address = self.college_id.email
        if not address:
            return False, False, _("College has no email address")
        template = self.env.ref(TPL_OVERDUE if kind == "overdue" else TPL_UPCOMING)
        template.send_mail(self.id, force_send=False)
        return True, address, False

    def _send_whatsapp(self, kind):
        """Send the reminder as a WhatsApp template. Returns the sender's result dict."""
        self.ensure_one()
        wa = self.env["otm.b2bfee.whatsapp"]
        college = self.college_id
        name = college.contact_person or college.name
        base = [name, self.term_name, self.program_id.name,
                format_date(self.env, self.due_date)]
        balance = formatLang(self.env, self.balance, currency_obj=self.currency_id)
        if kind == "overdue":
            params = base + [self.days_overdue, balance]
        else:
            params = base + [balance]
        return wa.send_template(college.whatsapp_number or college.phone, kind, params)

    def _schedule_task(self, user, summary, note):
        self.ensure_one()
        if not user:
            return False
        self.batch_id.activity_schedule(
            "mail.mail_activity_data_todo",
            date_deadline=fields.Date.context_today(self),
            summary=summary, note=note, user_id=user.id)
        return True

    def _summary_text(self):
        self.ensure_one()
        return _("%(college)s – %(term)s (%(batch)s): balance %(bal)s due %(due)s") % {
            "college": self.college_id.name, "term": self.term_name,
            "batch": self.batch_id.name, "bal": self.balance, "due": self.due_date}

    def _process_reminder(self, key, kind, conf, manual=False):
        """Send everything for one installment/trigger and write the log row."""
        self.ensure_one()
        email_sent, address, note = False, False, False
        if manual or conf["email_college"]:
            email_sent, address, note = self._queue_reminder_email(kind)
        wa = self._send_whatsapp(kind) if conf["wa_enabled"] else {}
        task = False
        escalated = False
        if manual or key == "due_today" or kind == "overdue":
            task = self._schedule_task(
                self._owner_user(), _("Fee follow-up: %s") % self.college_id.name,
                self._summary_text())
        if kind == "overdue" and not manual:
            late = self.days_overdue
            if late >= conf["escalate_from"]:
                owner = self._owner_user()
                managers = self._manager_users() - owner
                note_txt = _("%(summary)s. Overdue %(d)s days. College total pending: %(p)s") % {
                    "summary": self._summary_text(), "d": late,
                    "p": self.college_id.pending}
                for manager in managers:
                    self._schedule_task(
                        manager, _("Escalation: overdue fees – %s") % self.college_id.name,
                        note_txt)
                escalated = bool(managers)
        self.env["otm.b2bfee.reminder.log"].sudo().create({
            "installment_id": self.id, "trigger_key": key,
            "kind": "manual" if manual else kind,
            "email_sent": email_sent, "email_to": address,
            "wa_sent": wa.get("sent", False), "wa_to": wa.get("to", False),
            "wa_message_id": wa.get("message_id", False), "wa_note": wa.get("note", False),
            "activity_created": task, "escalated": escalated, "note": note})

    # ------------------------------------------------------------------ entry points
    @api.model
    def _cron_send_reminders(self):
        today = fields.Date.context_today(self)
        conf = self._notif_conf()
        Log = self.env["otm.b2bfee.reminder.log"].sudo()
        for rec in self.search([("state", "!=", "paid"), ("batch_id.state", "=", "running")]):
            trigger = rec._reminder_trigger(today, conf)
            if not trigger:
                continue
            key, kind = trigger
            if Log.search_count([("installment_id", "=", rec.id), ("trigger_key", "=", key)]):
                continue
            try:
                with self.env.cr.savepoint():
                    rec._process_reminder(key, kind, conf)
            except Exception:  # one bad record must not stop the run
                _logger.exception("B2B fee reminder failed for installment %s", rec.id)
        return True

    def action_send_reminder(self):
        conf = self._notif_conf()
        emailed = skipped = whatsapped = 0
        for rec in self:
            if rec.state == "paid":
                raise UserError(_("This installment is already paid."))
            kind = "overdue" if rec.state == "overdue" else "upcoming"
            stamp = fields.Datetime.now().strftime("%Y%m%d%H%M%S")
            rec._process_reminder("manual_%s" % stamp, kind, conf, manual=True)
            last = rec.log_ids.sorted("id")[-1]
            whatsapped += 1 if last.wa_sent else 0
            if last.email_sent:
                emailed += 1
            elif not last.wa_sent:
                skipped += 1
        message = _("%(e)s reminder email(s) queued.", e=emailed)
        if conf["wa_enabled"]:
            message += " " + _("%(w)s WhatsApp message(s) sent.", w=whatsapped)
        if skipped:
            message += " " + _("%(s)s not delivered on any channel (check email / WhatsApp number).", s=skipped)
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Reminder"), "message": message,
                       "type": "warning" if skipped else "success", "sticky": False},
        }
