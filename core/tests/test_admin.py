"""Admin question-distribution page and dashboard context."""

from django.test import Client, TestCase
from django.urls import reverse

from core.models import PlatformConfig, Project, User

from .helpers import make_project, make_user, set_distribution_mode


class QuestionDistributionViewTests(TestCase):
    def setUp(self):
        self.admin = make_user("distadmin", User.ADMIN)
        self.project = make_project("Dist", slug="dist", serving_weight=50)
        self.client = Client()
        self.client.force_login(self.admin)

    def test_switch_to_auto_mode(self):
        response = self.client.post(
            reverse("question_distribution"),
            {"action": "mode", "distribution_mode": PlatformConfig.AUTO},
        )
        self.assertRedirects(response, reverse("question_distribution"))
        self.assertEqual(PlatformConfig.load().distribution_mode, PlatformConfig.AUTO)

    def test_save_manual_weights(self):
        response = self.client.post(
            reverse("question_distribution"),
            {"action": "manual", f"weight_{self.project.id}": "75"},
        )
        self.assertRedirects(response, reverse("question_distribution"))
        self.project.refresh_from_db()
        self.assertEqual(self.project.serving_weight, 75)


class DashboardContextTests(TestCase):
    def setUp(self):
        self.admin = make_user("dashadmin", User.ADMIN)
        self.customer = make_user("dashcust", User.CUSTOMER)
        self.client = Client()
        self.client.force_login(self.admin)

    def test_dashboard_includes_pending_setup_count(self):
        make_project(
            "Pending customer project",
            slug="pending-cust",
            owner=self.customer,
            customer=self.customer.username,
            status=Project.PENDING,
            is_active=False,
        )
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pending_setup_count"], 1)


class ProjectEditPreviewTests(TestCase):
    def setUp(self):
        self.admin = make_user("previewadmin", User.ADMIN)
        self.client = Client()
        self.client.force_login(self.admin)
        self.project = make_project("Needs setup", slug="needs-setup", status=Project.PENDING, is_active=False)

    def test_pending_project_edit_includes_preview_context(self):
        response = self.client.get(reverse("project_edit", kwargs={"pk": self.project.pk}))
        self.assertEqual(response.status_code, 200)
        preview = response.context.get("pending_preview")
        self.assertIsNotNone(preview)
        self.assertEqual(preview["total_tasks"], 0)
