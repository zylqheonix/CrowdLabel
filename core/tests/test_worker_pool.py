"""Worker pool gating and task selection integration."""

from django.test import Client, TestCase
from django.urls import reverse

from core.models import PlatformConfig, Project, User, WorkerAnswer
from core.projects import resolve_project_scope, scoped_tasks_queryset
from core.views import _next_unanswered_task

from .helpers import make_project, make_task, make_user, set_distribution_mode


class WorkerPoolGateTests(TestCase):
    def setUp(self):
        self.active_project = make_project("Active", slug="active-proj")
        self.pending_project = make_project(
            "Pending",
            slug="pending-proj",
            status=Project.PENDING,
            is_active=False,
        )
        self.inactive_project = make_project(
            "Inactive",
            slug="inactive-proj",
            is_active=False,
        )
        make_task(self.active_project, task_id="active-task")
        make_task(self.pending_project, task_id="pending-task", is_active=False)
        make_task(self.inactive_project, task_id="inactive-task")

    def test_active_only_excludes_pending_and_inactive_projects(self):
        ids = set(scoped_tasks_queryset(active_only=True).values_list("task_id", flat=True))
        self.assertEqual(ids, {"active-task"})

    def test_inactive_task_flag_excluded_even_on_active_project(self):
        make_task(self.active_project, task_id="disabled-task", is_active=False)
        ids = set(scoped_tasks_queryset(active_only=True).values_list("task_id", flat=True))
        self.assertNotIn("disabled-task", ids)


class ProjectScopeTests(TestCase):
    def setUp(self):
        self.first = make_project("Alpha", slug="alpha")
        self.second = make_project("Beta", slug="beta", is_active=False)

    def test_defaults_to_first_active_project(self):
        project_id, selected, _ = resolve_project_scope({})
        self.assertEqual(project_id, self.first.id)
        self.assertEqual(selected, str(self.first.id))

    def test_all_scope_returns_none_id(self):
        project_id, selected, _ = resolve_project_scope({"project": "all"})
        self.assertIsNone(project_id)
        self.assertEqual(selected, "all")


class NextTaskSelectionTests(TestCase):
    def setUp(self):
        set_distribution_mode(PlatformConfig.MANUAL)
        self.worker = make_user("poolworker")
        self.project = make_project("Pool", slug="pool")
        self.task = make_task(self.project, task_id="pool-1", complexity=1)
        # Complete onboarding so worker_required does not redirect in integration tests.
        self.client = Client()
        self.client.force_login(self.worker)

    def test_next_unanswered_returns_eligible_easy_task(self):
        task = _next_unanswered_task(self.worker, "easy")
        self.assertEqual(task.pk, self.task.pk)

    def test_answered_tasks_are_skipped(self):
        WorkerAnswer.objects.create(
            user=self.worker,
            task=self.task,
            selected_answer="a",
            is_correct=True,
            verified=True,
        )
        self.assertIsNone(_next_unanswered_task(self.worker, "easy"))

    def test_tasks_page_shows_no_tasks_when_pool_empty(self):
        self.task.is_active = False
        self.task.save()
        session = self.client.session
        session["difficulty"] = "easy"
        session.save()
        response = self.client.get(reverse("tasks"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["no_tasks"])
