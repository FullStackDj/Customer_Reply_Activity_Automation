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

    @api.model
    def _customer_reply_deadline(self, rule, user):
        base_date = fields.Date.context_today(rule.with_context(tz=user.tz or self.env.context.get("tz")))
        return base_date + relativedelta(**{rule.deadline_unit: rule.deadline_count})

    @api.model
    def _customer_reply_activity_note(self, source_message, count, received_at):
        sender = source_message.email_from or self.env._("Unknown sender")
        subject = source_message.subject or self.env._("No subject")
        received = fields.Datetime.to_string(received_at)
        return Markup(
            "<p><strong>%s</strong></p>"
            "<ul>"
            "<li><strong>%s</strong> %s</li>"
            "<li><strong>%s</strong> %s</li>"
            "<li><strong>%s</strong> %s</li>"
            "<li><strong>%s</strong> %s</li>"
            "</ul>"
        ) % (
            self.env._("Customer reply received"),
            self.env._("From:"),
            sender,
            self.env._("Subject:"),
            subject,
            self.env._("Received:"),
            received,
            self.env._("Replies in this activity:"),
            count,
        )

    @api.model
    def _customer_reply_sender_is_internal(self, sender, author_id=False):
        partner = self.env["res.partner"].sudo().browse(author_id).exists()
        if partner:
            partner_users = partner.with_context(active_test=False).user_ids
            if any(user._is_internal() for user in partner_users):
                return True

        normalized = email_normalize(sender, strict=False)
        if not normalized:
            return False
        matching_users = self.env["res.users"].sudo().with_context(active_test=False).search(
            [("partner_id.email_normalized", "=", normalized)]
        )
        return any(user._is_internal() for user in matching_users)

    @api.model
    def _customer_reply_address_is_excluded(self, sender, patterns):
        normalized = email_normalize(sender, strict=False)
        if not normalized:
            return False
        _local_part, separator, domain = normalized.partition("@")
        if not separator:
            return False

        for raw_pattern in re.split(r"[\s,;]+", patterns or ""):
            pattern = raw_pattern.strip().lower()
            if not pattern:
                continue
            if pattern.startswith("@"):
                if fnmatchcase(domain, pattern[1:]):
                    return True
            elif "@" not in pattern:
                if fnmatchcase(domain, pattern):
                    return True
            elif fnmatchcase(normalized, pattern):
                return True
        return False

    @api.model
    def _customer_reply_is_automatic(self, message):
        auto_submitted = self._customer_reply_header_values(message, "Auto-Submitted")
        if any(value.split(";", 1)[0].strip() not in {"", "no"} for value in auto_submitted):
            return True

        precedence = {
            token
            for value in self._customer_reply_header_values(message, "Precedence")
            for token in re.split(r"[\s,;]+", value)
            if token
        }
        if precedence.intersection({"auto-reply", "auto_reply", "bulk", "junk", "list"}):
            return True

        automatic_headers = {
            "X-Autoreply",
            "X-Auto-Reply",
            "X-Autorespond",
            "X-Autoresponse",
            "X-Auto-Response",
            "X-Auto-Response-From",
            "X-Autoreply-From",
            "X-Mail-Autoreply",
            "X-MS-Exchange-Inbox-Rules-Loop",
            "X-MS-Exchange-Generated-Message-Source",
            "X-Loop",
            "List-Id",
            "List-Unsubscribe",
        }
        if any(self._customer_reply_header_values(message, header) for header in automatic_headers):
            return True

        return_path = self._customer_reply_header_values(message, "Return-Path")
        if any(value.replace(" ", "") == "<>" for value in return_path):
            return True
        return message.get_content_type() == "multipart/report"

    @api.model
    def _customer_reply_header_values(self, message, header):
        return [str(value).strip().lower() for value in message.get_all(header, [])]

    @api.model
    def _customer_reply_advisory_lock(self, namespace, *parts):
        source = "\x1f".join(
            [self.env.cr.dbname, "mail_customer_reply_activity", namespace, *(str(part) for part in parts)]
        )
        lock_key = int.from_bytes(
            hashlib.blake2b(source.encode(), digest_size=8).digest(),
            byteorder="big",
            signed=True,
        )
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])