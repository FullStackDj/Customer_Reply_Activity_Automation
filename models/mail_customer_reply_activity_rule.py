from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MailCustomerReplyActivityRule(models.Model):
    _name = "mail.customer.reply.activity.rule"
    _description = "Customer Reply Activity Rule"
    _order = "sequence, model_id"
    _rec_name = "name"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        required=True,
        ondelete="cascade",
        domain=[
            ("is_mail_thread", "=", True),
            ("is_mail_activity", "=", True),
            ("transient", "=", False),
        ],
    )
    name = fields.Char(
        related="model_id.name",
    )
    model = fields.Char(
        related="model_id.model",
        string="Technical Model",
        store=True,
        index=True,
    )
    responsible_field_id = fields.Many2one(
        "ir.model.fields",
        string="Responsible Field",
        required=True,
        ondelete="cascade",
    )
    fallback_user_id = fields.Many2one(
        "res.users",
        string="Fallback Responsible",
        ondelete="restrict",
        domain=[
            ("share", "=", False),
            ("active", "=", True),
        ],
        help="Used when the configured responsible field has no active internal users.",
    )
    activity_type_id = fields.Many2one(
        "mail.activity.type",
        string="Activity Type",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.ref(
            "mail_customer_reply_activity.mail_activity_type_customer_reply",
            raise_if_not_found=False,
        ),
    )
    deadline_count = fields.Integer(
        string="Reaction Time",
        required=True,
        default=0,
    )
    deadline_unit = fields.Selection(
        [
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        string="Reaction Unit",
        required=True,
        default="days",
    )
    merge_replies = fields.Boolean(
        string="Merge Replies",
        default=True,
        help="Keep one open activity per record and responsible user while counting later replies.",
    )
    ignore_automatic_messages = fields.Boolean(
        string="Ignore Automatic Messages",
        default=True,
        help="Ignore auto-replies, bulk messages, mailing lists, delivery reports, and loop-generated messages.",
    )
    excluded_addresses = fields.Text(
        string="Excluded Addresses",
        default=lambda self: "\n".join(
            [
                "no-reply@*",
                "noreply@*",
                "do-not-reply@*",
                "donotreply@*",
                "mailer-daemon@*",
                "postmaster@*",
            ]
        ),
        help=(
            "One sender address or pattern per line. Wildcards, @domain, domain-only, comma, "
            "and semicolon formats are supported."
        ),
    )

    _active_model_unique = models.UniqueIndex(
        "(model_id) WHERE active",
        "Only one active customer reply rule can be configured per model.",
    )
    _deadline_count_nonnegative = models.Constraint(
        "CHECK(deadline_count >= 0)",
        "Reaction time cannot be negative.",
    )