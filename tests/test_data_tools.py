# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDataTools(TransactionCase):

    def _settings(self):
        return self.env["res.config.settings"].create({})

    def test_01_load_remove_demo_keeps_own_data(self):
        own = self.env["otm.b2bfee.college"].create({"name": "Own College DT"})
        s = self._settings()
        if self.env.ref("otm_b2b_fee_tracker.demo_college_thomas", raise_if_not_found=False):
            s.action_b2bfee_remove_demo()
        s.action_b2bfee_load_demo()
        self.assertTrue(self.env.ref("otm_b2b_fee_tracker.demo_college_thomas"))
        self.assertGreater(self.env["otm.b2bfee.payment"].search_count([]), 0)
        with self.assertRaises(UserError):
            s.action_b2bfee_load_demo()
        s.action_b2bfee_remove_demo()
        self.assertFalse(self.env.ref("otm_b2b_fee_tracker.demo_college_thomas", raise_if_not_found=False))
        self.assertTrue(own.exists())
        self.assertFalse(self.env["otm.b2bfee.payment"].search([("college_id.name", "ilike", "Thomas")]))
        with self.assertRaises(UserError):
            s.action_b2bfee_remove_demo()
        s.action_b2bfee_load_demo()  # reload works after removal

    def test_02_remove_all(self):
        s = self._settings()
        if not self.env.ref("otm_b2b_fee_tracker.demo_college_thomas", raise_if_not_found=False):
            s.action_b2bfee_load_demo()
        s.action_b2bfee_remove_all()
        for m in ("college", "batch", "student", "installment", "payment", "program"):
            self.assertEqual(self.env["otm.b2bfee.%s" % m].search_count([]), 0, m)

    def test_03_users_cannot(self):
        user = self.env["res.users"].create({
            "name": "DT User", "login": "dt_user",
            "group_ids": [(4, self.env.ref("otm_b2b_fee_tracker.group_b2bfee_user").id)]})
        s = self.env["res.config.settings"].with_user(user).new({})
        with self.assertRaises(AccessError):
            s.action_b2bfee_remove_all()
