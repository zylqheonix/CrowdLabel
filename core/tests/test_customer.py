"""Customer upload, isolation, deadline requests, and admin activation."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Project, Task, User
from core.projects import pending_customer_setup_projects, scoped_tasks_queryset

from .helpers import make_project, make_task, make_user


CUSTOMER_CSV_ROW = (
    "task_id,lang,category,type,topic,complexity,image,task,choices,correct_answer\n"
    'cust-1,en,cat,mcq,topic1,1,,Question?,"{""a"": ""Yes"", ""b"": ""No""}",a\n'
)


class CustomerUploadTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = make_user("cust", User.CUSTOMER)
        self.client.force_login(self.customer)

    def _upload(self, csv_text=CUSTOMER_CSV_ROW, **extra):
        data = {
            "name": "Customer Project",
            "deadline": (timezone.localdate().replace(year=timezone.localdate().year + 1)).isoformat(),
            "csv_file": SimpleUploadedFile(
                "tasks.csv",
                csv_text.encode("utf-8"),
                content_type="text/csv",
            ),
        }
        data.update(extra)
        return self.client.post(reverse("customer_upload"), data)

    def test_successful_upload_creates_pending_inactive_project(self):
        response = self._upload()
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name="Customer Project")
        self.assertEqual(project.status, Project.PENDING)
        self.assertFalse(project.is_active)
        self.assertEqual(project.owner, self.customer)
        task = Task.objects.get(task_id="cust-1")
        self.assertFalse(task.is_active)
        self.assertTrue(task.is_goldtask)

    def test_upload_without_rows_deletes_project(self):
        empty_csv = "task_id,lang,category,type,topic,complexity,image,task,choices,correct_answer\n"
        response = self._upload(csv_text=empty_csv)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.filter(name="Customer Project").exists())

    def test_pending_tasks_excluded_from_worker_pool(self):
        self._upload()
        project = Project.objects.get(name="Customer Project")
        self.assertEqual(
            scoped_tasks_queryset(active_only=True).filter(project=project).count(),
            0,
        )

    def test_upload_report_surfaces_in_project_detail_after_redirect(self):
        bad_row = "bad-1,en,cat,mcq,topic,1,,Question,bad-json,a\n"
        csv_text = CUSTOMER_CSV_ROW + bad_row
        response = self._upload(csv_text=csv_text)
        self.assertEqual(response.status_code, 302)
        detail_response = self.client.get(response.url)
        self.assertEqual(detail_response.status_code, 200)
        report = detail_response.context.get("upload_report")
        self.assertIsNotNone(report)
        self.assertEqual(report["imported"], 1)
        self.assertEqual(report["skipped"], 1)


class CustomerIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = make_user("owner", User.CUSTOMER)
        self.other = make_user("other", User.CUSTOMER)
        self.project = make_project(
            "Owned",
            slug="owned",
            owner=self.owner,
            customer=self.owner.username,
            status=Project.PENDING,
            is_active=False,
        )

    def test_other_customer_cannot_view_project_detail(self):
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("customer_project_detail", kwargs={"pk": self.project.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_owner_can_view_project_detail(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("customer_project_detail", kwargs={"pk": self.project.pk})
        )
        self.assertEqual(response.status_code, 200)


class DeadlineRequestTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = make_user("cust2", User.CUSTOMER)
        self.project = make_project(
            "Deadline Proj",
            slug="deadline-proj",
            owner=self.customer,
            customer=self.customer.username,
            status=Project.ACTIVE,
            is_active=True,
            deadline=timezone.localdate(),
        )
        self.client.force_login(self.customer)

    def test_customer_can_submit_deadline_request(self):
        new_deadline = (timezone.localdate().replace(year=timezone.localdate().year + 2)).isoformat()
        response = self.client.post(
            reverse("customer_project_detail", kwargs={"pk": self.project.pk}),
            {
                "action": "deadline_request",
                "requested_deadline": new_deadline,
                "deadline_request_note": "Need more time",
            },
        )
        self.assertRedirects(
            response,
            reverse("customer_project_detail", kwargs={"pk": self.project.pk}),
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.deadline_request_status, Project.DEADLINE_REQUEST_PENDING)
        self.assertEqual(str(self.project.requested_deadline), new_deadline)


class AdminActivationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = make_user("adm", User.ADMIN)
        self.customer = make_user("cust3", User.CUSTOMER)
        self.project = make_project(
            "Awaiting",
            slug="awaiting",
            owner=self.customer,
            customer=self.customer.username,
            status=Project.PENDING,
            is_active=False,
        )
        make_task(self.project, task_id="pending-task", is_active=False)
        self.client.force_login(self.admin)

    def test_activate_action_enables_worker_pool(self):
        response = self.client.post(
            reverse("project_edit", kwargs={"pk": self.project.pk}),
            {"action": "activate"},
        )
        self.assertRedirects(response, reverse("project_edit", kwargs={"pk": self.project.pk}))
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.ACTIVE)
        self.assertTrue(self.project.is_active)
        self.assertIsNotNone(self.project.activated_at)
        self.assertIsNone(self.project.customer_activation_seen_at)
        task = Task.objects.get(task_id="pending-task")
        self.assertTrue(task.is_active)
        self.assertEqual(scoped_tasks_queryset(active_only=True).filter(project=self.project).count(), 1)

    def test_pending_setup_projects_lists_customer_uploads(self):
        rows = list(pending_customer_setup_projects())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].pk, self.project.pk)

    def test_admin_approves_deadline_request(self):
        requested = timezone.localdate().replace(year=timezone.localdate().year + 1)
        self.project.requested_deadline = requested
        self.project.deadline_request_status = Project.DEADLINE_REQUEST_PENDING
        self.project.save()
        response = self.client.post(
            reverse("project_edit", kwargs={"pk": self.project.pk}),
            {"action": "approve_deadline"},
        )
        self.assertRedirects(response, reverse("project_edit", kwargs={"pk": self.project.pk}))
        self.project.refresh_from_db()
        self.assertEqual(self.project.deadline, requested)
        self.assertEqual(self.project.deadline_request_status, Project.DEADLINE_REQUEST_HANDLED)


class CustomerActivationNotificationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.customer = make_user("cust-notify", User.CUSTOMER)
        self.project = make_project(
            "Recently activated",
            slug="recently-activated",
            owner=self.customer,
            customer=self.customer.username,
            status=Project.ACTIVE,
            is_active=True,
            activated_at=timezone.now(),
            customer_activation_seen_at=None,
        )
        self.client.force_login(self.customer)

    def test_dashboard_surfaces_and_marks_activation_notice(self):
        response = self.client.get(reverse("customer_dashboard"))
        self.assertEqual(response.status_code, 200)
        notices = response.context["newly_activated_projects"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].pk, self.project.pk)
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.customer_activation_seen_at)

    def test_activation_notice_shown_once(self):
        self.client.get(reverse("customer_dashboard"))
        second = self.client.get(reverse("customer_dashboard"))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.context["newly_activated_projects"], [])
