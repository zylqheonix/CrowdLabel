"""Registration, login redirects, and role guards."""

from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.auth_data import REGISTERABLE_ROLES, ROLE_REDIRECTS
from core.models import User

from .helpers import make_user


def _otp_from_last_email():
    body = mail.outbox[-1].body
    import re

    match = re.search(r"\b(\d{6})\b", body)
    assert match, f"No OTP found in email body: {body!r}"
    return match.group(1)


class RegisterableRolesTests(TestCase):
    def test_allowlist_matches_product_roles(self):
        self.assertEqual(REGISTERABLE_ROLES, frozenset({"worker", "customer"}))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_worker_registration_requires_one_time_email_verification(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse("register"),
            {
                "username": "newworker",
                "email": "newworker@example.com",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("verify_worker_signup_otp"))
        user = User.objects.get(username="newworker")
        self.assertEqual(user.role, User.WORKER)
        self.assertEqual(user.email, "newworker@example.com")
        self.assertFalse(user.worker_email_verified)
        self.assertEqual(len(mail.outbox), 1)

        code = _otp_from_last_email()
        verify = self.client.post(reverse("verify_worker_signup_otp"), {"code": code})
        self.assertRedirects(verify, reverse("worker_setup"))
        user.refresh_from_db()
        self.assertTrue(user.worker_email_verified)
        self.assertTrue(self.client.session.get("pending_onboarding"))

    def test_customer_registration_requires_one_time_email_verification(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse("register"),
            {
                "username": "newcustomer",
                "email": "newcustomer@example.com",
                "password": "qorvex88",
                "role": User.CUSTOMER,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("verify_customer_signup_otp"))
        user = User.objects.get(username="newcustomer")
        self.assertEqual(user.role, User.CUSTOMER)
        self.assertFalse(user.customer_email_verified)
        self.assertEqual(len(mail.outbox), 1)

        code = _otp_from_last_email()
        verify = self.client.post(reverse("verify_customer_signup_otp"), {"code": code})
        self.assertRedirects(verify, reverse("customer_dashboard"))
        user.refresh_from_db()
        self.assertTrue(user.customer_email_verified)
        self.assertNotIn("pending_onboarding", self.client.session)

    def test_registration_requires_email(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "noemail",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="noemail").exists())

    def test_duplicate_email_rejected_across_accounts(self):
        self.client.post(
            reverse("register"),
            {
                "username": "firstuser",
                "email": "shared@example.com",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        response = self.client.post(
            reverse("register"),
            {
                "username": "seconduser",
                "email": "shared@example.com",
                "password": "qorvex88",
                "role": User.CUSTOMER,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="seconduser").exists())

    def test_duplicate_email_case_insensitive(self):
        self.client.post(
            reverse("register"),
            {
                "username": "caseuser1",
                "email": "Case@Example.com",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        response = self.client.post(
            reverse("register"),
            {
                "username": "caseuser2",
                "email": "case@example.com",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="caseuser2").exists())

    def test_admin_role_post_rejected(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "fakeadmin",
                "password": "qorvex88",
                "role": User.ADMIN,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="fakeadmin").exists())

    def test_registration_rejects_weak_password(self):
        mail.outbox.clear()
        for weak in ("short7", "12345678", "password"):
            response = self.client.post(
                reverse("register"),
                {
                    "username": "weakworker",
                    "email": "weakworker@example.com",
                    "password": weak,
                    "role": User.WORKER,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("error", response.context)
            self.assertFalse(User.objects.filter(username="weakworker").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_role_query_defaults_to_worker(self):
        response = self.client.get(reverse("register"), {"role": User.ADMIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_role"], User.WORKER)

    def test_customer_register_legacy_url_redirects(self):
        response = self.client.get(reverse("customer_register"))
        self.assertRedirects(
            response,
            f"{reverse('register')}?role={User.CUSTOMER}",
            fetch_redirect_response=False,
        )

    def test_worker_signup_resend_is_rate_limited_to_30_seconds(self):
        mail.outbox.clear()
        self.client.post(
            reverse("register"),
            {
                "username": "cooldownworker",
                "email": "cooldownworker@example.com",
                "password": "qorvex88",
                "role": User.WORKER,
            },
        )
        self.assertEqual(len(mail.outbox), 1)
        response = self.client.post(
            reverse("verify_worker_signup_otp"),
            {"action": "resend"},
            follow=True,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(
            response,
            "Please wait",
        )


class LoginRedirectTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_worker_logs_in_without_2fa(self):
        user = make_user("workerlogin", User.WORKER, email="workerlogin@example.com")
        response = self.client.post(
            reverse("login"),
            {"username": user.username, "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("worker_dashboard"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_unverified_worker_is_forced_through_one_time_verification(self):
        user = make_user("unverified", User.WORKER, email="unverified@example.com")
        user.worker_email_verified = False
        user.save(update_fields=["worker_email_verified"])

        response = self.client.post(
            reverse("login"),
            {"username": user.username, "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("verify_worker_signup_otp"))
        code = _otp_from_last_email()
        verify = self.client.post(reverse("verify_worker_signup_otp"), {"code": code})
        self.assertRedirects(verify, reverse("worker_setup"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_admin_and_customer_require_login_2fa(self):
        for role, view_name in (
            (User.ADMIN, "dashboard"),
            (User.CUSTOMER, "customer_dashboard"),
        ):
            with self.subTest(role=role):
                mail.outbox.clear()
                user = make_user(f"otp_{role}", role, email=f"otp_{role}@example.com")
                self.client.logout()
                response = self.client.post(
                    reverse("login"),
                    {"username": user.username, "password": "pass12345"},
                )
                self.assertRedirects(response, reverse("verify_login_otp"))
                self.assertEqual(len(mail.outbox), 1)
                code = _otp_from_last_email()
                verify = self.client.post(reverse("verify_login_otp"), {"code": code})
                self.assertRedirects(verify, reverse(view_name))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_unverified_customer_is_forced_through_signup_verification(self):
        user = make_user("unverifiedcust", User.CUSTOMER, email="unverifiedcust@example.com")
        user.customer_email_verified = False
        user.save(update_fields=["customer_email_verified"])

        response = self.client.post(
            reverse("login"),
            {"username": user.username, "password": "pass12345"},
        )
        self.assertRedirects(response, reverse("verify_customer_signup_otp"))
        code = _otp_from_last_email()
        verify = self.client.post(reverse("verify_customer_signup_otp"), {"code": code})
        self.assertRedirects(verify, reverse("customer_dashboard"))
        user.refresh_from_db()
        self.assertTrue(user.customer_email_verified)


class RoleGuardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.worker = make_user("worker1", User.WORKER)
        self.admin = make_user("admin1", User.ADMIN)
        self.customer = make_user("customer1", User.CUSTOMER)

    def _status_for(self, user, url_name, **kwargs):
        self.client.force_login(user)
        return self.client.get(reverse(url_name, kwargs=kwargs)).status_code

    def test_worker_cannot_access_admin_dashboard(self):
        self.assertEqual(self._status_for(self.worker, "dashboard"), 403)

    def test_customer_cannot_access_worker_dashboard(self):
        self.assertEqual(self._status_for(self.customer, "worker_dashboard"), 403)

    def test_worker_cannot_access_customer_upload(self):
        self.assertEqual(self._status_for(self.worker, "customer_upload"), 403)

    def test_admin_cannot_access_customer_dashboard(self):
        self.assertEqual(self._status_for(self.admin, "customer_dashboard"), 403)

    def test_pending_onboarding_redirects_worker_from_dashboard(self):
        self.client.force_login(self.worker)
        session = self.client.session
        session["pending_onboarding"] = True
        session.save()
        response = self.client.get(reverse("worker_dashboard"))
        self.assertRedirects(response, reverse("worker_setup"))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.worker = make_user("recoverme", User.WORKER, email="recoverme@example.com")
        self.customer = make_user(
            "recovercust", User.CUSTOMER, email="recovercust@example.com"
        )

    def test_worker_can_reset_password_via_email_otp(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse("forgot_password"),
            {"email": self.worker.email},
        )
        self.assertRedirects(response, reverse("verify_reset_otp"))
        code = _otp_from_last_email()
        verify = self.client.post(reverse("verify_reset_otp"), {"code": code})
        self.assertRedirects(verify, reverse("reset_password"))
        reset = self.client.post(
            reverse("reset_password"),
            {"password": "newpass99", "password_confirm": "newpass99"},
        )
        self.assertRedirects(reset, reverse("login"))
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password("newpass99"))

    def test_reset_rejects_weak_password(self):
        mail.outbox.clear()
        self.client.post(reverse("forgot_password"), {"email": self.worker.email})
        code = _otp_from_last_email()
        self.client.post(reverse("verify_reset_otp"), {"code": code})
        response = self.client.post(
            reverse("reset_password"),
            {"password": "password", "password_confirm": "password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("error", response.context)
        self.worker.refresh_from_db()
        self.assertFalse(self.worker.check_password("password"))

    def test_customer_can_reset_password_via_email_otp(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse("forgot_password"),
            {"email": self.customer.email},
        )
        self.assertRedirects(response, reverse("verify_reset_otp"))
        code = _otp_from_last_email()
        verify = self.client.post(reverse("verify_reset_otp"), {"code": code})
        self.assertRedirects(verify, reverse("reset_password"))
        reset = self.client.post(
            reverse("reset_password"),
            {"password": "newpass99", "password_confirm": "newpass99"},
        )
        self.assertRedirects(reset, reverse("login"))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password("newpass99"))

    def test_admin_cannot_reset_via_email_otp(self):
        admin = make_user("bossadmin", User.ADMIN, email="bossadmin@example.com")
        mail.outbox.clear()
        response = self.client.post(
            reverse("forgot_password"),
            {"email": admin.email},
        )
        # Same generic redirect + no email sent — admins can't self-recover and
        # the response must not reveal that the account exists.
        self.assertRedirects(response, reverse("verify_reset_otp"))
        self.assertEqual(len(mail.outbox), 0)

    def test_forgot_password_does_not_reveal_missing_accounts(self):
        mail.outbox.clear()
        response = self.client.post(
            reverse("forgot_password"),
            {"email": "nobody@example.com"},
        )
        self.assertRedirects(response, reverse("verify_reset_otp"))
        self.assertEqual(len(mail.outbox), 0)

        verify = self.client.get(reverse("verify_reset_otp"))
        self.assertEqual(verify.status_code, 200)
        self.assertContains(verify, "If an account exists")
