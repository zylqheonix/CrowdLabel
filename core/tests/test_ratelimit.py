"""Rate limiting on auth and hammerable endpoints."""

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import User
from core.ratelimit import rate_limit_key

from .helpers import make_user


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RATE_LIMITS={
        "login_ip": (2, 900),
        "login_fail": (2, 900),
        "register": (2, 3600),
        "otp_send_ip": (2, 3600),
        "otp_send_user": (2, 3600),
        "otp_verify_fail": (2, 900),
        "forgot_password": (2, 3600),
        "forgot_password_email": (2, 3600),
        "reset_password": (2, 3600),
        "task_submit": (2, 60),
        "activity_month": (2, 60),
        "analytics": (2, 60),
        "csv_upload": (2, 3600),
        "store_buy": (2, 60),
        "invite_create": (2, 3600),
        "review_resolve": (2, 60),
    },
)
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_login_ip_rate_limited(self):
        for _ in range(2):
            self.client.post(
                reverse("login"),
                {"username": "nobody", "password": "wrong"},
            )
        response = self.client.post(
            reverse("login"),
            {"username": "nobody", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many requests")

    def test_register_rate_limited(self):
        for index in range(2):
            self.client.post(
                reverse("register"),
                {
                    "username": f"user{index}",
                    "email": f"user{index}@example.com",
                    "password": "qorvex88",
                    "role": User.CUSTOMER,
                },
            )
        response = self.client.post(
            reverse("register"),
            {
                "username": "user3",
                "email": "user3@example.com",
                "password": "qorvex88",
                "role": User.CUSTOMER,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many requests")

    def test_otp_verify_lockout_after_failures(self):
        mail.outbox.clear()
        self.client.post(
            reverse("register"),
            {
                "username": "otpuser",
                "email": "otpuser@example.com",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        for _ in range(2):
            response = self.client.post(
                reverse("verify_worker_signup_otp"),
                {"code": "000000"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Invalid or expired code")

        response = self.client.post(
            reverse("verify_worker_signup_otp"),
            {"code": "000000"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many requests")

    def test_forgot_password_rate_limited(self):
        make_user("worker", User.WORKER, email="worker@example.com")
        for _ in range(2):
            self.client.post(reverse("forgot_password"), {"email": "worker@example.com"})
        response = self.client.post(
            reverse("forgot_password"),
            {"email": "worker@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many requests")

    def test_activity_month_json_rate_limited(self):
        worker = make_user("activity", User.WORKER)
        self.client.force_login(worker)
        for _ in range(2):
            response = self.client.get(reverse("worker_activity_month"))
            self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("worker_activity_month"))
        self.assertEqual(response.status_code, 429)

    def test_analytics_rate_limited(self):
        admin = make_user("adminrl", User.ADMIN)
        self.client.force_login(admin)
        for _ in range(2):
            response = self.client.get(reverse("analytics"))
            self.assertEqual(response.status_code, 200)
        response = self.client.get(reverse("analytics"))
        self.assertEqual(response.status_code, 429)

    def test_rate_limit_keys_are_hashed(self):
        key = rate_limit_key("login_ip", "203.0.113.1")
        self.assertTrue(key.startswith("rl:login_ip:"))
        self.assertNotIn("203.0.113.1", key)
