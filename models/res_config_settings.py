# -*- coding: utf-8 -*-
import re

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import convert_file

YES_NO = [("yes", "Yes"), ("no", "No")]


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    group_b2bfee_students = fields.Boolean(
        string="Student Entry",
        implied_group="otm_b2b_fee_tracker.group_b2bfee_student_entry")
    b2bfee_due_window_days = fields.Integer(
        string="Due-soon Window (days)",
        config_parameter="otm_b2b_fee_tracker.due_window_days", default=7)
    b2bfee_reminder_before = fields.Char(
        string="Reminder Days Before Due",
        config_parameter="otm_b2b_fee_tracker.reminder_before_days", default="7,3")
    b2bfee_overdue_days = fields.Char(
        string="Overdue Reminder Days After Due",
        config_parameter="otm_b2b_fee_tracker.overdue_days", default="1,7,15")
    b2bfee_escalate_from = fields.Integer(
        string="Escalate to Managers After (days overdue)",
        config_parameter="otm_b2b_fee_tracker.escalate_from_days", default=7)
    b2bfee_email_college = fields.Selection(
        YES_NO, string="Email Reminders to College",
        config_parameter="otm_b2b_fee_tracker.email_college", default="yes")
    b2bfee_email_receipt = fields.Selection(
        YES_NO, string="Email Receipt on Posting",
        config_parameter="otm_b2b_fee_tracker.email_receipt", default="yes")

    # ---- WhatsApp (Meta Cloud API)
    b2bfee_wa_enabled = fields.Selection(
        YES_NO, string="Send WhatsApp Reminders",
        config_parameter="otm_b2b_fee_tracker.wa_enabled", default="no")
    b2bfee_wa_receipt = fields.Selection(
        YES_NO, string="WhatsApp Receipt on Posting",
        config_parameter="otm_b2b_fee_tracker.wa_receipt", default="yes")
    b2bfee_wa_phone_number_id = fields.Char(
        string="Phone Number ID", config_parameter="otm_b2b_fee_tracker.wa_phone_number_id")
    b2bfee_wa_token = fields.Char(
        string="Access Token", config_parameter="otm_b2b_fee_tracker.wa_token")
    b2bfee_wa_api_version = fields.Char(
        string="Graph API Version",
        config_parameter="otm_b2b_fee_tracker.wa_api_version", default="v21.0")
    b2bfee_wa_language = fields.Char(
        string="Template Language",
        config_parameter="otm_b2b_fee_tracker.wa_language", default="en")
    b2bfee_wa_country_code = fields.Char(
        string="Default Country Code",
        config_parameter="otm_b2b_fee_tracker.wa_country_code", default="91")
    b2bfee_wa_tpl_upcoming = fields.Char(
        string="Template: Upcoming / Due",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_upcoming")
    b2bfee_wa_tpl_overdue = fields.Char(
        string="Template: Overdue",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_overdue")
    b2bfee_wa_tpl_receipt = fields.Char(
        string="Template: Receipt",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_receipt")
    b2bfee_wa_tpl_summary = fields.Char(
        string="Team Summary Template",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_summary")
    b2bfee_wa_tpl_staff_payment = fields.Char(
        string="Team Payment Alert Template",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_staff_payment")
    b2bfee_wa_tpl_staff_escalation = fields.Char(
        string="Team Escalation Template",
        config_parameter="otm_b2b_fee_tracker.wa_tpl_staff_escalation")
    b2bfee_wa_test_number = fields.Char(string="Test Number")

    def set_values(self):
        for rec in self:
            for fname in ("b2bfee_wa_tpl_upcoming", "b2bfee_wa_tpl_overdue", "b2bfee_wa_tpl_receipt",
                          "b2bfee_wa_tpl_summary", "b2bfee_wa_tpl_staff_payment",
                          "b2bfee_wa_tpl_staff_escalation"):
                value = (rec[fname] or "").strip()
                if value and not re.fullmatch(r"[a-z0-9_]{1,512}", value):
                    raise UserError(_(
                        "'%(field)s' must be a WhatsApp template name: only lowercase letters, "
                        "numbers and underscores (for example b2bfee_team_summary), exactly as "
                        "shown in WhatsApp Manager. You entered: %(value)s",
                        field=rec._fields[fname].string, value=value[:60]))
                rec[fname] = value
        return super().set_values()

    def action_b2bfee_wa_test(self):
        """Save the settings, then send the 'upcoming' template to a test number."""
        self.ensure_one()
        self.set_values()
        wa = self.env["otm.b2bfee.whatsapp"]
        result = wa.send_template(
            self.b2bfee_wa_test_number, "upcoming",
            ["Test", "Term 1", "Demo Program", fields.Date.to_string(fields.Date.today()), "1,000.00"])
        message = ("Test message sent to %s." % result["to"]) if result["sent"] \
            else ("Not sent: %s" % result["note"])
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": "WhatsApp test", "message": message,
                       "type": "success" if result["sent"] else "danger", "sticky": not result["sent"]},
        }

    # ------------------------------------------------------------------
    # Demo data and data clean-up
    # ------------------------------------------------------------------
    def _b2bfee_check_manager(self):
        if not self.env.user.has_group("otm_b2b_fee_tracker.group_b2bfee_manager"):
            raise AccessError(self.env._("Only B2B Fee managers can load or remove data."))

    def _b2bfee_demo_ids(self, model):
        data = self.env["ir.model.data"].sudo().search([
            ("module", "=", "otm_b2b_fee_tracker"), ("model", "=", model),
            ("name", "=like", "demo\\_%")])
        return data.mapped("res_id")

    def _b2bfee_notify(self, message, kind="success"):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": kind, "sticky": False,
                       "next": {"type": "ir.actions.client", "tag": "reload"}},
        }

    def action_b2bfee_load_demo(self):
        self.ensure_one()
        self._b2bfee_check_manager()
        if self._b2bfee_demo_ids("otm.b2bfee.college"):
            raise UserError(self.env._("Demo data is already loaded. Remove it first to reload."))
        convert_file(self.sudo().env, "otm_b2b_fee_tracker", "data/demo_data.xml",
                     {}, mode="init", noupdate=True, kind="demo")
        return self._b2bfee_notify(self.env._("Demo data loaded."))

    def _b2bfee_wipe(self, demo_only):
        """Delete fee data with SQL: payments are locked against unlink on purpose."""
        cr = self.env.cr
        Model = self.env
        if demo_only:
            colleges = self._b2bfee_demo_ids("otm.b2bfee.college")
            programs = self._b2bfee_demo_ids("otm.b2bfee.program")
            batches = Model["otm.b2bfee.batch"].sudo().with_context(active_test=False).search(
                ["|", ("id", "in", self._b2bfee_demo_ids("otm.b2bfee.batch")),
                 ("college_id", "in", colleges)]).ids
        else:
            colleges = Model["otm.b2bfee.college"].sudo().with_context(active_test=False).search([]).ids
            programs = Model["otm.b2bfee.program"].sudo().with_context(active_test=False).search([]).ids
            batches = Model["otm.b2bfee.batch"].sudo().search([]).ids
        pays = Model["otm.b2bfee.payment"].sudo().search(
            ["|", ("batch_id", "in", batches), ("college_id", "in", colleges)]).ids
        insts = Model["otm.b2bfee.installment"].sudo().search([("batch_id", "in", batches)]).ids
        steps = [
            ("otm_b2bfee_payment_alloc", "payment_id = ANY(%s) OR installment_id = ANY(%s)", (pays, insts)),
            ("otm_b2bfee_reminder_log", "installment_id = ANY(%s)", (insts,)),
            ("otm_b2bfee_payment", "id = ANY(%s)", (pays,)),
            ("otm_b2bfee_installment", "id = ANY(%s)", (insts,)),
            ("otm_b2bfee_plan_line", "batch_id = ANY(%s)", (batches,)),
            ("otm_b2bfee_student", "batch_id = ANY(%s)", (batches,)),
            ("otm_b2bfee_batch", "id = ANY(%s)", (batches,)),
            ("otm_b2bfee_college", "id = ANY(%s)", (colleges,)),
            ("otm_b2bfee_program", "id = ANY(%s)", (programs,)),
        ]
        models = {
            "otm_b2bfee_payment": ("otm.b2bfee.payment", pays),
            "otm_b2bfee_installment": ("otm.b2bfee.installment", insts),
            "otm_b2bfee_batch": ("otm.b2bfee.batch", batches),
            "otm_b2bfee_college": ("otm.b2bfee.college", colleges),
        }
        # chatter, activities and external ids that point at the rows
        for model, ids in models.values():
            cr.execute("DELETE FROM mail_message WHERE model = %s AND res_id = ANY(%s)", (model, ids))
            cr.execute("DELETE FROM mail_activity WHERE res_model = %s AND res_id = ANY(%s)", (model, ids))
            cr.execute("DELETE FROM mail_followers WHERE res_model = %s AND res_id = ANY(%s)", (model, ids))
        for table, where, params in steps:
            cr.execute("DELETE FROM %s WHERE %s" % (table, where), params)
        cr.execute("""DELETE FROM ir_model_data WHERE module = 'otm_b2b_fee_tracker'
                      AND model LIKE 'otm.b2bfee.%%' AND name LIKE 'demo\\_%%'""")
        self.env.invalidate_all()
        return len(colleges), len(batches), len(pays)

    def action_b2bfee_remove_demo(self):
        self.ensure_one()
        self._b2bfee_check_manager()
        if not self._b2bfee_demo_ids("otm.b2bfee.college"):
            raise UserError(self.env._("There is no demo data to remove."))
        colleges, batches, pays = self._b2bfee_wipe(demo_only=True)
        return self._b2bfee_notify(self.env._(
            "Demo data removed: %(c)s colleges, %(b)s batches, %(p)s payments. Your own data was not touched.",
            c=colleges, b=batches, p=pays))

    def action_b2bfee_remove_all(self):
        self.ensure_one()
        self._b2bfee_check_manager()
        colleges, batches, pays = self._b2bfee_wipe(demo_only=False)
        return self._b2bfee_notify(self.env._(
            "All fee data deleted: %(c)s colleges, %(b)s batches, %(p)s payments.",
            c=colleges, b=batches, p=pays), "warning")
