from odoo import fields, models


class MailActivity(models.Model):
    _inherit = "mail.activity"

    customer_reply_rule_id = fields.Many2one(
        "mail.customer.reply.activity.rule",
        string="Customer Reply Rule",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    customer_reply_count = fields.Integer(
        string="Customer Reply Count",
        readonly=True,
        copy=False,
        default=0,
    )
    customer_reply_last_message_id = fields.Many2one(
        "mail.message",
        string="Latest Customer Reply",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    customer_reply_last_received_at = fields.Datetime(
        string="Latest Customer Reply Received",
        readonly=True,
        copy=False,
    )

    _customer_reply_open_index = models.Index(
        "(customer_reply_rule_id, res_model, res_id, user_id) WHERE active AND customer_reply_rule_id IS NOT NULL"
    )
