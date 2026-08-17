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