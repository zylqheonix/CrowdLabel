"""Security helper coverage: redirects, session wipe, answer uniqueness."""

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import EmailOTP, WorkerAnswer
from core.security import invalidate_user_sessions, safe_next_url
from core.two_factor import create_and_send_otp

from .helpers import make_project, make_task, make_user


class SafeNextUrlTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_allows_same_host_relative_path(self):
        request = self.factory.get("/admin-tools/tasks/1/")
        request.META["HTTP_HOST"] = "testserver"
        self.assertEqual(
            safe_next_url(request, "/admin-tools/review-queue/", "/fallback/"),
            "/admin-tools/review-queue/",
        )

    def test_rejects_external_host(self):
        request = self.factory.get("/admin-tools/tasks/1/")
        request.META["HTTP_HOST"] = "testserver"
        self.assertEqual(
            safe_next_url(request, "https://evil.example/phish", "/fallback/"),
            "/fallback/",
        )

    def test_admin_task_detail_ignores_external_next(self):
        admin = make_user("secadmin", role="admin")
        project = make_project("Sec", slug="sec")
        task = make_task(project, task_id="sec-1")
        client = Client()
        client.force_login(admin)
        response = client.get(
            reverse("admin_task_detail", kwargs={"pk": task.pk}),
            {"next": "https://evil.example/phish"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["back_url"], reverse("review_queue"))
        self.assertContains(response, f'href="{reverse("review_queue")}"')


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetSessionInvalidationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.worker = make_user("resetsess", role="worker", email="resetsess@example.com")

    def test_password_reset_clears_existing_sessions(self):
        store = SessionStore()
        store["_auth_user_id"] = str(self.worker.pk)
        store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        store.create()
        self.assertTrue(Session.objects.filter(session_key=store.session_key).exists())

        create_and_send_otp(self.worker, EmailOTP.PURPOSE_PASSWORD_RESET)
        from django.core import mail
        import re

        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        session = self.client.session
        session["pending_login_user_id"] = self.worker.id
        session.save()
        self.client.post(reverse("verify_reset_otp"), {"code": code})
        self.client.post(
            reverse("reset_password"),
            {"password": "brandnew99", "password_confirm": "brandnew99"},
        )

        self.assertFalse(Session.objects.filter(session_key=store.session_key).exists())
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.check_password("brandnew99"))


class UniqueWorkerAnswerTests(TestCase):
    def setUp(self):
        self.user = make_user("uniqans")
        self.project = make_project("Uniq", slug="uniq")
        self.task = make_task(self.project, task_id="uniq-1")

    def test_second_answer_for_same_task_rejected(self):
        WorkerAnswer.objects.create(
            user=self.user,
            task=self.task,
            selected_answer="a",
            is_correct=True,
            verified=True,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WorkerAnswer.objects.create(
                    user=self.user,
                    task=self.task,
                    selected_answer="b",
                    is_correct=False,
                    verified=True,
                )

    def test_invalidate_user_sessions_helper(self):
        other = make_user("otheruniq")
        keep = SessionStore()
        keep["_auth_user_id"] = str(self.user.pk)
        keep.create()
        drop = SessionStore()
        drop["_auth_user_id"] = str(self.user.pk)
        drop.create()
        other_store = SessionStore()
        other_store["_auth_user_id"] = str(other.pk)
        other_store.create()

        invalidate_user_sessions(self.user, keep_session_key=keep.session_key)
        self.assertTrue(Session.objects.filter(session_key=keep.session_key).exists())
        self.assertFalse(Session.objects.filter(session_key=drop.session_key).exists())
        self.assertTrue(Session.objects.filter(session_key=other_store.session_key).exists())
