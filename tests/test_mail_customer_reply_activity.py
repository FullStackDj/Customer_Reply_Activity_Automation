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