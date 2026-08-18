{
    "name": "Customer Reply Activity Automation",
    "version": "19.0.1.0.0",
    "summary": "Turn customer and vendor email replies into assigned activities, deadlines, and notifications",
    "description": """
Customer Reply Activity Automation converts eligible external email replies from
customers, vendors, and suppliers into assigned Odoo activities with response
deadlines, reply details, and user notifications. It helps teams prevent missed
messages, unanswered chatter replies, and delayed customer or vendor follow-up.

Configure reply automation for CRM leads and opportunities, quotations, Sales
Orders, Purchase Orders, invoices, delivery orders, pickings, project tasks, and
custom models that support Odoo chatter and activities. Each model can use its own
responsible user field, fallback responsible, activity type, reaction time, reply
merge policy, automatic-message filter, and sender exclusions.

Assign activities through Many2one or Many2many user fields. The module supports
salespeople, buyers, assignees, responsible users, several internal users, and a
fallback user when the document has no valid owner. Every activity contains the
sender, subject, received time, reply count, latest reply details, and a clear
response deadline.

Merge repeated customer replies into one open activity without postponing its
original deadline, or create a separate activity for every reply. When a customer
replies after the previous activity has been completed, the module creates a new
follow-up activity with a new deadline and notification.

Ignore internal employee replies, automatic replies, mailing-list emails, delivery
reports, mail loops, no-reply senders, exact email addresses, domains, and wildcard
patterns. Eligible external replies remain available in the original document
chatter while standard Odoo incoming mail routing, messages, activities, and
notifications continue to work normally.

Use the module for customer email follow-up, vendor and supplier reply tracking,
chatter activity automation, response deadline management, missed email prevention,
activity assignment, reply reminders, and notifications across Odoo business
documents.
""",
    "category": "Productivity/Discuss",
    "license": "LGPL-3",
    "author": "full.stack.odoo@gmail.com",
    "depends": ["mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/mail_activity_type_data.xml",
        "views/mail_customer_reply_activity_rule_views.xml",
        "views/res_config_settings_views.xml",
        "views/mail_menus.xml",
    ],
    "images": ["static/description/main_screenshot.png"],
    "installable": True,
    "application": True,
}