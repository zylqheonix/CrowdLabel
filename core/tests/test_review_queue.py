"""Review queue flags, resolution persistence, and filters."""

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Task, User, WorkerAnswer
from core.review_queue import (
    FLAG_CROWD_DISAGREEMENT,
    FLAG_CROWD_VS_TRUTH,
    FLAG_GOLD_FAILURE,
    build_review_queue,
    build_resolve_context,
)

from .helpers import make_project, make_task, make_user, query_get


class ReviewFlagTests(TestCase):
    def setUp(self):
        self.project = make_project("Review", slug="review")

    def _answers(self, task, selections):
        for index, choice in enumerate(selections):
            worker = make_user(f"revworker_{task.task_id}_{index}")
            WorkerAnswer.objects.create(
                user=worker,
                task=task,
                selected_answer=choice,
                is_correct=choice == task.correct_answer if task.correct_answer else None,
                verified=bool(task.correct_answer),
            )

    def test_crowd_vs_truth_flag_when_majority_wrong(self):
        task = make_task(
            self.project,
            task_id="crowd-wrong",
            correct_answer="a",
            is_goldtask=False,
        )
        self._answers(task, ["b", "b", "b"])
        rows, _, _, _ = build_review_queue(query_get(project="all"))
        row = next(r for r in rows if r["task_id"] == "crowd-wrong")
        self.assertIn(FLAG_CROWD_VS_TRUTH, row["flags"])

    def test_disagreement_flag_on_low_agreement(self):
        task = make_task(
            self.project,
            task_id="disagree",
            correct_answer=None,
            is_goldtask=False,
        )
        self._answers(task, ["a", "b", "c"])
        rows, _, _, _ = build_review_queue(query_get(project="all"))
        row = next(r for r in rows if r["task_id"] == "disagree")
        self.assertIn(FLAG_CROWD_DISAGREEMENT, row["flags"])

    def test_gold_failure_flag(self):
        task = make_task(
            self.project,
            task_id="gold-fail",
            correct_answer="a",
            is_goldtask=True,
        )
        self._answers(task, ["b", "b", "b"])
        rows, _, _, _ = build_review_queue(query_get(project="all"))
        row = next(r for r in rows if r["task_id"] == "gold-fail")
        self.assertIn(FLAG_GOLD_FAILURE, row["flags"])


class ResolutionFilterTests(TestCase):
    def setUp(self):
        self.project = make_project("Resolve", slug="resolve")
        self.resolved = make_task(
            self.project,
            task_id="resolved-task",
            is_goldtask=False,
            correct_answer=None,
            admin_resolved_answer="a",
            resolved_at=timezone.now(),
        )
        self.resolved.resolved_by = make_user("resolver", User.ADMIN)
        self.resolved.save()
        self.unresolved = make_task(
            self.project,
            task_id="open-task",
            is_goldtask=False,
            correct_answer=None,
        )

    def test_resolved_filter(self):
        rows, _, _, _ = build_review_queue(query_get(project="all", resolution="resolved"))
        task_ids = {row["task_id"] for row in rows}
        self.assertEqual(task_ids, {"resolved-task"})

    def test_unresolved_filter_excludes_gold(self):
        gold = make_task(
            self.project,
            task_id="gold-open",
            is_goldtask=True,
            correct_answer="a",
        )
        rows, _, _, _ = build_review_queue(query_get(project="all", resolution="unresolved"))
        task_ids = {row["task_id"] for row in rows}
        self.assertIn("open-task", task_ids)
        self.assertNotIn("resolved-task", task_ids)
        self.assertNotIn("gold-open", task_ids)


class ResolveViewTests(TestCase):
    def setUp(self):
        self.admin = make_user("revadmin", User.ADMIN)
        self.project = make_project("ResolveView", slug="resolve-view")
        self.task = make_task(
            self.project,
            task_id="resolve-me",
            is_goldtask=False,
            correct_answer=None,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_save_resolution_persists_on_task(self):
        response = self.client.post(
            reverse("resolve_review_item", kwargs={"pk": self.task.pk}),
            {"action": "save", "admin_answer": "a"},
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.admin_resolved_answer, "a")
        self.assertEqual(self.task.resolved_by, self.admin)
        self.assertIsNotNone(self.task.resolved_at)

    def test_clear_resolution_removes_fields(self):
        self.task.admin_resolved_answer = "b"
        self.task.resolved_by = self.admin
        self.task.resolved_at = timezone.now()
        self.task.save()
        response = self.client.post(
            reverse("resolve_review_item", kwargs={"pk": self.task.pk}),
            {"action": "clear"},
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.admin_resolved_answer)
        self.assertIsNone(self.task.resolved_by)
        self.assertIsNone(self.task.resolved_at)

    def test_invalid_answer_not_saved(self):
        response = self.client.post(
            reverse("resolve_review_item", kwargs={"pk": self.task.pk}),
            {"action": "save", "admin_answer": "z"},
        )
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.admin_resolved_answer)

    def test_build_resolve_context_includes_choice_map(self):
        context = build_resolve_context(self.task)
        self.assertIn("a", context["choice_map"])
        self.assertIn("b", context["choice_map"])
