import email
import email.policy
from unittest import SkipTest

from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("mail_customer_reply_activity", "post_install", "-at_install")
class TestMailCustomerReplyActivity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_user = new_test_user(
            cls.env,
            login="customer.reply.test@example.com",
            groups="base.group_user",
            name="Customer Reply Test User",
            email="customer.reply.internal@example.com",
        )

        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.responsible_field = cls.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "main_user_id")],
            limit=1,
        )

        if (
            not cls.partner_model.is_mail_thread
            or not cls.partner_model.is_mail_activity
            or not cls.responsible_field
        ):
            raise SkipTest("The Odoo 19 contact mail test model is unavailable")

        cls.activity_type = cls.env.ref(
            "mail_customer_reply_activity.mail_activity_type_customer_reply"
        )
        cls.rule = cls.env["mail.customer.reply.activity.rule"].create(
            {
                "model_id": cls.partner_model.id,
                "responsible_field_id": cls.responsible_field.id,
                "fallback_user_id": cls.test_user.id,
                "activity_type_id": cls.activity_type.id,
            }
        )
        cls.target = cls.test_user.partner_id

    def _email(self, extra_headers="", content_type="text/plain"):
        raw = (
            "From: Customer <customer@example.com>\r\n"
            "To: replies@example.com\r\n"
            "Subject: Re: Proposal\r\n"
            "Message-Id: <customer-reply@example.com>\r\n"
            f"Content-Type: {content_type}\r\n"
            f"{extra_headers}"
            "\r\n"
            "Reply body"
        )
        return email.message_from_string(raw, policy=email.policy.SMTP)

    def _post_parent_message(self, target=None):
        return (target or self.target).message_post(
            body="Proposal",
            subject="Proposal",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )

    def _process_reply(
        self,
        parent,
        message_id,
        sender="customer@example.com",
        extra_headers="",
    ):
        raw = (
            f"From: Customer <{sender}>\r\n"
            "To: replies@example.com\r\n"
            "Subject: Re: Proposal\r\n"
            f"Message-Id: <{message_id}>\r\n"
            f"In-Reply-To: {parent.message_id}\r\n"
            f"References: {parent.message_id}\r\n"
            f"{extra_headers}"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "\r\n"
            "Customer reply"
        )
        self.env["mail.thread"].sudo().message_process(None, raw)

    def _activities(self, target=None):
        target = target or self.target
        return self.env["mail.activity"].with_context(active_test=False).search(
            [
                ("customer_reply_rule_id", "=", self.rule.id),
                ("res_model", "=", target._name),
                ("res_id", "=", target.id),
            ],
            order="id",
        )

    def test_activity_type_is_available(self):
        self.assertTrue(self.activity_type.active)
        self.assertFalse(self.activity_type.res_model)

    def test_automatic_message_headers(self):
        thread = self.env["mail.thread"]

        self.assertFalse(thread._customer_reply_is_automatic(self._email()))
        self.assertFalse(
            thread._customer_reply_is_automatic(
                self._email("Auto-Submitted: no\r\n")
            )
        )
        self.assertTrue(
            thread._customer_reply_is_automatic(
                self._email("Auto-Submitted: auto-replied\r\n")
            )
        )
        self.assertTrue(
            thread._customer_reply_is_automatic(
                self._email("Precedence: bulk\r\n")
            )
        )
        self.assertTrue(
            thread._customer_reply_is_automatic(
                self._email("X-Autoreply: yes\r\n")
            )
        )
        self.assertTrue(
            thread._customer_reply_is_automatic(
                self._email("List-Id: customers.example.com\r\n")
            )
        )
        self.assertFalse(
            thread._customer_reply_is_automatic(
                self._email("X-Auto-Response-Suppress: All\r\n")
            )
        )

    def test_excluded_address_patterns(self):
        thread = self.env["mail.thread"]
        patterns = (
            "exact@example.com\n"
            "@blocked.example\n"
            "*.notifications.example\n"
            "no-reply@*"
        )

        self.assertTrue(
            thread._customer_reply_address_is_excluded(
                "exact@example.com", patterns
            )
        )
        self.assertTrue(
            thread._customer_reply_address_is_excluded(
                "user@blocked.example", patterns
            )
        )
        self.assertTrue(
            thread._customer_reply_address_is_excluded(
                "robot@eu.notifications.example", patterns
            )
        )
        self.assertTrue(
            thread._customer_reply_address_is_excluded(
                "no-reply@allowed.example", patterns
            )
        )
        self.assertFalse(
            thread._customer_reply_address_is_excluded(
                "customer@allowed.example", patterns
            )
        )

    def test_internal_sender_detection(self):
        thread = self.env["mail.thread"]

        self.assertTrue(
            thread._customer_reply_sender_is_internal(
                self.test_user.email,
                self.test_user.partner_id.id,
            )
        )
        self.assertFalse(
            thread._customer_reply_sender_is_internal(
                "new.customer@example.invalid"
            )
        )

    def test_external_reply_creates_and_merges_activity(self):
        parent = self._post_parent_message()

        self._process_reply(parent, "customer-reply-1@example.com")
        activities = self._activities()

        self.assertEqual(len(activities), 1)
        self.assertTrue(activities.active)
        self.assertEqual(activities.user_id, self.test_user)
        self.assertEqual(activities.customer_reply_count, 1)
        self.assertEqual(
            activities.summary,
            "Customer replied — response required",
        )

        first_deadline = activities.date_deadline

        self._process_reply(parent, "customer-reply-2@example.com")
        activities = self._activities()

        self.assertEqual(len(activities), 1)
        self.assertEqual(activities.customer_reply_count, 2)
        self.assertEqual(activities.date_deadline, first_deadline)
        self.assertEqual(
            activities.customer_reply_last_message_id.message_id,
            "<customer-reply-2@example.com>",
        )

    def test_completed_activity_is_not_merged(self):
        parent = self._post_parent_message()

        self._process_reply(parent, "customer-reply-done-1@example.com")
        first_activity = self._activities()
        first_activity.action_done()

        self.assertFalse(first_activity.active)

        self._process_reply(parent, "customer-reply-done-2@example.com")
        activities = self._activities()

        self.assertEqual(len(activities), 2)
        self.assertEqual(len(activities.filtered("active")), 1)