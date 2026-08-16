{
    "name": "Customer Reply Activity Automation",
    "version": "19.0.1.0.0",
    "summary": "Create assigned activities for customer and vendor email replies in chatter",
    "description": """
Turn external customer and vendor email replies into assigned activities with
deadlines, notifications, reply merging, fallback assignment, exclusions, and
automatic-message filtering. Works with CRM, Sales, Purchase, Invoicing,
Inventory, Project, and custom chatter-enabled models.
""",
    "category": "Productivity/Discuss",
    "license": "LGPL-3",
    "author": "full.stack.odoo@gmail.com",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/mail_activity_type_data.xml",
        "views/res_config_settings_views.xml",
        "views/mail_menus.xml",
    ],
    "installable": True,
    "application": True,
}
