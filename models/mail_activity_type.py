from odoo import models
from odoo.exceptions import ValidationError


class MailActivityType(models.Model):
    _inherit = "mail.activity.type"

    def write(self, vals):
        result = super().write(vals)
        if {"active", "res_model"}.intersection(vals) and not self.env.context.get("_force_unlink"):
            rules = self.env["mail.customer.reply.activity.rule"].sudo().search(
                [("activity_type_id", "in", self.ids)]
            )
            rules._check_activity_type_model()
        return result

    def unlink(self):
        if not self.env.context.get("_force_unlink"):
            rules = self.env["mail.customer.reply.activity.rule"].sudo().search(
                [("activity_type_id", "in", self.ids)],
                limit=1,
            )
            if rules:
                raise ValidationError(
                    self.env._("An activity type used by a customer reply rule cannot be deleted.")
                )
        return super().unlink()
