from fnmatch import fnmatchcase
import hashlib
import logging
import re

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools.mail import email_normalize


_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    @api.model
    def _message_route_process(self, message, message_dict, routes):
        candidates = []
        try:
            with self.env.cr.savepoint():
                candidates = self._customer_reply_get_candidates(message_dict, routes)
        except Exception:
            _logger.exception("Failed to prepare customer reply activity candidates")

        if candidates:
            try:
                with self.env.cr.savepoint():
                    self._customer_reply_advisory_lock("message", message_dict.get("message_id") or "")
                    duplicate = self.env["mail.message"].sudo().search(
                        [("message_id", "=", message_dict.get("message_id"))],
                        limit=1,
                    )
            except Exception:
                candidates = []
                _logger.exception("Failed to lock customer reply activity processing")
            else:
                if duplicate:
                    _logger.info(
                        "Ignored duplicated customer reply with Message-Id %s during route processing",
                        message_dict.get("message_id"),
                    )
                    return False

        result = super()._message_route_process(message, message_dict, routes)

        for rule, model_name, record_id in candidates:
            try:
                with self.env.cr.savepoint():
                    self._customer_reply_process_candidate(
                        message,
                        message_dict,
                        rule,
                        model_name,
                        record_id,
                    )
            except Exception:
                _logger.exception(
                    "Failed to create customer reply activity for %s,%s using rule %s",
                    model_name,
                    record_id,
                    rule.id,
                )

        return result

    @api.model
    def _customer_reply_get_candidates(self, message_dict, routes):
        if message_dict.get("message_type") != "email" or message_dict.get("is_internal"):
            return []
        parent_id = message_dict.get("parent_id")
        if not parent_id:
            return []
        parent = self.env["mail.message"].sudo().browse(parent_id).exists()
        if not parent or not parent.model or not parent.res_id:
            return []

        route_keys = {
            (route[0], route[1])
            for route in routes or ()
            if len(route) == 5 and route[1] and route[0] == parent.model and route[1] == parent.res_id
        }
        if not route_keys:
            return []

        rules = self.env["mail.customer.reply.activity.rule"].sudo().search(
            [("active", "=", True), ("model", "in", list({key[0] for key in route_keys}))]
        )
        rules_by_model = {rule.model: rule for rule in rules}
        return [
            (rules_by_model[model_name], model_name, record_id)
            for model_name, record_id in sorted(route_keys)
            if model_name in rules_by_model
        ]

    @api.model
    def _customer_reply_process_candidate(self, message, message_dict, rule, model_name, record_id):
        rule = rule.exists()
        if not rule or not rule.active or model_name not in self.env:
            return
        record = self.env[model_name].sudo().browse(record_id).exists()
        if not record or not hasattr(record, "activity_schedule"):
            return

        source_message = self.env["mail.message"].sudo().search(
            [
                ("message_id", "=", message_dict.get("message_id")),
                ("model", "=", model_name),
                ("res_id", "=", record_id),
                ("message_type", "=", "email"),
            ],
            order="id desc",
            limit=1,
        )
        if not source_message or source_message.is_internal:
            return
        if rule.ignore_automatic_messages and self._customer_reply_is_automatic(message):
            return

        sender = email_normalize(source_message.email_from or message_dict.get("email_from"), strict=False)
        if not sender:
            _logger.warning(
                "Skipped customer reply activity for %s,%s because the sender address is invalid",
                model_name,
                record_id,
            )
            return
        if self._customer_reply_address_is_excluded(sender, rule.excluded_addresses):
            return
        if self._customer_reply_sender_is_internal(sender, source_message.author_id.id):
            return

        activity_type = rule.activity_type_id
        if not activity_type.active or activity_type.res_model not in {False, model_name}:
            _logger.warning(
                "Skipped customer reply activity for %s,%s because rule %s has an invalid activity type",
                model_name,
                record_id,
                rule.id,
            )
            return

        users = self._customer_reply_get_responsible_users(rule, record)
        if not users:
            _logger.warning(
                "Skipped customer reply activity for %s,%s because rule %s has no responsible user",
                model_name,
                record_id,
                rule.id,
            )
            return

        for user in users:
            try:
                with self.env.cr.savepoint():
                    self._customer_reply_schedule_activity(rule, record, user, source_message)
            except Exception:
                _logger.exception(
                    "Failed to schedule customer reply activity for %s,%s and user %s",
                    model_name,
                    record_id,
                    user.id,
                )

    @api.model
    def _customer_reply_get_responsible_users(self, rule, record):
        field_name = rule.responsible_field_id.name
        field = record._fields.get(field_name)
        users = self.env["res.users"].sudo().with_context(active_test=False)
        if field and field.type in {"many2one", "many2many"} and field.comodel_name == "res.users":
            configured_users = record[field_name].sudo().with_context(active_test=False)
            users = configured_users.filtered(lambda user: user.active and user._is_internal())

        fallback = rule.fallback_user_id.sudo().with_context(active_test=False)
        if not users and fallback and fallback.active and fallback._is_internal():
            users = fallback

        unique_ids = sorted(set(users.ids))
        return self.env["res.users"].sudo().with_context(active_test=False).browse(unique_ids)

    @api.model
    def _customer_reply_schedule_activity(self, rule, record, user, source_message):
        activity = self.env["mail.activity"].sudo()
        if rule.merge_replies:
            self._customer_reply_advisory_lock(
                "activity",
                rule.id,
                record._name,
                record.id,
                user.id,
            )
            activity = self.env["mail.activity"].sudo().search(
                [
                    ("active", "=", True),
                    ("customer_reply_rule_id", "=", rule.id),
                    ("res_model", "=", record._name),
                    ("res_id", "=", record.id),
                    ("user_id", "=", user.id),
                ],
                order="id",
                limit=1,
            )

        received_at = fields.Datetime.now()
        count = (activity.customer_reply_count or 1) + 1 if activity else 1
        note = self._customer_reply_activity_note(source_message, count, received_at)
        values = {
            "activity_type_id": rule.activity_type_id.id,
            "summary": self.env._("Customer replied — response required"),
            "note": note,
            "customer_reply_count": count,
            "customer_reply_last_message_id": source_message.id,
            "customer_reply_last_received_at": received_at,
        }

        if activity:
            activity.write(values)
        else:
            activity = record.with_context(
                mail_activity_automation_skip=False,
                mail_activity_quick_update=True,
            ).activity_schedule(
                date_deadline=self._customer_reply_deadline(rule, user),
                user_id=user.id,
                customer_reply_rule_id=rule.id,
                **values,
            )

        if activity:
            try:
                with self.env.cr.savepoint():
                    activity.sudo().action_notify()
            except Exception:
                _logger.exception("Failed to notify user %s about customer reply activity %s", user.id, activity.id)

        return activity