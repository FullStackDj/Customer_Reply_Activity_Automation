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

    @api.onchange("model_id")
    def _onchange_model_id(self):
        for rule in self:
            if rule.responsible_field_id.model_id != rule.model_id:
                rule.responsible_field_id = False
            if (
                rule.activity_type_id.res_model
                and rule.activity_type_id.res_model != rule.model
            ):
                rule.activity_type_id = False

    @api.constrains("model_id")
    def _check_model_capabilities(self):
        for rule in self:
            if (
                not rule.model_id.is_mail_thread
                or not rule.model_id.is_mail_activity
                or rule.model_id.transient
            ):
                raise ValidationError(
                    self.env._(
                        "The selected model must support both chatter and activities "
                        "and must not be transient."
                    )
                )

            if rule.model not in self.env:
                raise ValidationError(
                    self.env._(
                        "The selected model is not available in the current registry."
                    )
                )

    @api.constrains("model_id", "responsible_field_id")
    def _check_responsible_field(self):
        for rule in self:
            field = rule.responsible_field_id

            if (
                field.model_id != rule.model_id
                or field.ttype not in {"many2one", "many2many"}
                or field.relation != "res.users"
            ):
                raise ValidationError(
                    self.env._(
                        "The responsible field must belong to the selected model "
                        "and point to Users."
                    )
                )

    @api.constrains("fallback_user_id")
    def _check_fallback_user(self):
        for rule in self:
            user = rule.fallback_user_id

            if user and (not user.active or not user._is_internal()):
                raise ValidationError(
                    self.env._(
                        "The fallback responsible must be an active internal user."
                    )
                )

    @api.constrains("model_id", "activity_type_id")
    def _check_activity_type_model(self):
        for rule in self:
            activity_type = rule.activity_type_id

            if activity_type and not activity_type.active:
                raise ValidationError(
                    self.env._("The activity type must be active.")
                )

            if (
                activity_type
                and activity_type.res_model
                and activity_type.res_model != rule.model
            ):
                raise ValidationError(
                    self.env._(
                        "The activity type must be generic or configured "
                        "for the selected model."
                    )
                )