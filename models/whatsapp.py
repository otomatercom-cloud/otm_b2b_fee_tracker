# -*- coding: utf-8 -*-
import logging
import re

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

PARAM = "otm_b2b_fee_tracker."
GRAPH_URL = "https://graph.facebook.com/%(version)s/%(phone_id)s/messages"
TEMPLATE_NAME_RE = re.compile(r"[a-z0-9_]{1,512}")
TEMPLATE_KEYS = {
    "upcoming": "wa_tpl_upcoming",
    "overdue": "wa_tpl_overdue",
    "receipt": "wa_tpl_receipt",
    "summary": "wa_tpl_summary",
    "staff_payment": "wa_tpl_staff_payment",
    "staff_escalation": "wa_tpl_staff_escalation",
}


class B2bFeeWhatsapp(models.AbstractModel):
    """Sends approved WhatsApp *template* messages through the Meta Cloud API.

    Never raises: callers get a result dict and decide what to log, so a Meta
    outage can never block posting a payment or the daily reminder run.
    """
    _name = "otm.b2bfee.whatsapp"
    _description = "B2B Fee WhatsApp Sender (Meta Cloud API)"

    @api.model
    def _conf(self):
        icp = self.env["ir.config_parameter"].sudo()

        def get(key, default=""):
            return icp.get_param(PARAM + key) or default

        return {
            "enabled": get("wa_enabled", "no") == "yes",
            "receipt": get("wa_receipt", "yes") == "yes",
            "phone_id": get("wa_phone_number_id").strip(),
            "token": get("wa_token").strip(),
            "version": get("wa_api_version", "v21.0").strip(),
            "language": get("wa_language", "en").strip(),
            "country_code": re.sub(r"\D", "", get("wa_country_code", "91")) or "91",
            "templates": {kind: get(key).strip() for kind, key in TEMPLATE_KEYS.items()},
        }

    @api.model
    def normalize_number(self, raw, country_code="91"):
        """Digits only, with country code. Returns False when it cannot be a mobile number."""
        digits = re.sub(r"\D", "", raw or "").lstrip("0")
        if len(digits) == 10:
            digits = country_code + digits
        return digits if 11 <= len(digits) <= 15 else False

    @api.model
    def clean_param(self, value):
        """Meta rejects newlines, tabs and long runs of spaces inside template parameters."""
        text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
        return (text or "-")[:1000]

    @api.model
    def send_template(self, raw_number, kind, params):
        """Send the configured template of `kind` (see TEMPLATE_KEYS).

        Returns {"sent": bool, "to": str|False, "message_id": str|False, "note": str|False}.
        """
        result = {"sent": False, "to": False, "message_id": False, "note": False}
        conf = self._conf()
        if not conf["enabled"]:
            result["note"] = "WhatsApp is disabled in settings"
            return result
        if not (conf["phone_id"] and conf["token"]):
            result["note"] = "WhatsApp phone number ID or access token is not configured"
            return result
        template = conf["templates"].get(kind)
        if not template:
            result["note"] = "No WhatsApp template name configured for '%s'" % kind
            return result
        if not TEMPLATE_NAME_RE.fullmatch(template):
            result["note"] = ("Invalid WhatsApp template name '%s'. Use only lowercase letters, "
                              "numbers and underscores, exactly as shown in WhatsApp Manager."
                              % template[:60])
            return result
        number = self.normalize_number(raw_number, conf["country_code"])
        if not number:
            result["note"] = "No valid WhatsApp number"
            return result
        result["to"] = number

        payload = {
            "messaging_product": "whatsapp",
            "to": number,
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": conf["language"]},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": self.clean_param(p)} for p in params],
                }],
            },
        }
        url = GRAPH_URL % {"version": conf["version"], "phone_id": conf["phone_id"]}
        try:
            response = requests.post(
                url, json=payload, timeout=10,
                headers={"Authorization": "Bearer " + conf["token"]})
            try:
                body = response.json()
            except ValueError:
                body = {}
            if response.status_code in (200, 201) and body.get("messages"):
                result["sent"] = True
                result["message_id"] = body["messages"][0].get("id")
                return result
            error = (body.get("error") or {}).get("message") or (response.text or "")[:200]
            result["note"] = ("Meta API error %s: %s [template '%s', language '%s']" % (
                response.status_code, error, template, conf["language"]))[:400]
        except Exception as exc:  # network, timeout, bad JSON... never block the caller
            result["note"] = ("WhatsApp request failed: %s" % exc)[:250]
        _logger.warning("B2B fee WhatsApp to %s failed: %s", number, result["note"])
        return result
