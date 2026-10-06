# -*- coding: utf-8 -*-
{
    "name": "B2B College Fee Tracker",
    "version": "19.0.1.0.0",
    "summary": "Track term-wise fee collection from B2B partner colleges",
    "description": """
Phase 1: College master, program batches, student registration, term-wise
payment plan, auto-generated installments, college-level payments with
FIFO allocation and daily installment status refresh.
    """,
    "author": "Otomater",
    "website": "https://otomater.com",
    "license": "OPL-1",
    "category": "Sales",
    "depends": ["base", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence_data.xml",
        "data/cron_data.xml",
        "report/payment_receipt.xml",
        "data/mail_template_data.xml",
        "views/college_views.xml",
        "views/program_views.xml",
        "views/batch_views.xml",
        "views/student_views.xml",
        "views/installment_views.xml",
        "views/payment_views.xml",
        "views/reminder_log_views.xml",
        "views/staff_views.xml",
        "views/res_config_settings_views.xml",
        "views/dashboard_views.xml",
        "views/menus.xml",
    ],
    "demo": [
        "data/demo_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "otm_b2b_fee_tracker/static/src/dashboard/dashboard.js",
            "otm_b2b_fee_tracker/static/src/dashboard/college_dashboard.js",
            "otm_b2b_fee_tracker/static/src/dashboard/dashboard.xml",
            "otm_b2b_fee_tracker/static/src/dashboard/dashboard.css",
        ],
    },
    "application": True,
    "installable": True,
}
