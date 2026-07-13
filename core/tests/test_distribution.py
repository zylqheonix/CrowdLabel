"""Question distribution — manual weights, auto throughput, deficit picker."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.distribution import (
    auto_throughput,
    build_distribution_page_context,
    compute_project_weights,
    pick_task_by_project_deficit,
    remaining_task_count,
)
from core.models import PlatformConfig, WorkerAnswer
from core.projects import scoped_tasks_queryset

from .helpers import make_project, make_task, make_user, set_distribution_mode


class ManualWeightTests(TestCase):
    def setUp(self):
        set_distribution_mode(PlatformConfig.MANUAL)
        self.projects = [
            make_project("P80", slug="p80", serving_weight=80),
            make_project("P10a", slug="p10a", serving_weight=10),
            make_project("P10b", slug="p10b", serving_weight=10),
        ]
        for project in self.projects:
            make_task(project, task_id=f"{project.slug}-t1", complexity=1)

    def test_compute_project_weights_manual(self):
        weights = compute_project_weights()
        self.assertEqual(weights[self.projects[0]], 80.0)
        self.assertEqual(weights[self.projects[1]], 10.0)
        self.assertEqual(weights[self.projects[2]], 10.0)

    def test_normalized_percentages_sum_to_100(self):
        context = build_distribution_page_context()
        by_slug = {
            row["project"].slug: row["normalized_pct"]
            for row in context["project_rows"]
        }
        self.assertEqual(by_slug["p80"], 80.0)
        self.assertEqual(by_slug["p10a"], 10.0)
        self.assertEqual(by_slug["p10b"], 10.0)


class AutoThroughputTests(TestCase):
    def setUp(self):
        set_distribution_mode(PlatformConfig.AUTO)
        self.project = make_project("Auto", slug="auto", serving_boost=2.0)

    def test_no_deadline_uses_urgency_constant(self):
        throughput = auto_throughput(self.project, remaining=10)
        self.assertEqual(throughput, 5.0)

    def test_deadline_divides_remaining_by_days(self):
        self.project.deadline = timezone.localdate() + timedelta(days=5)
        self.project.save()
        throughput = auto_throughput(self.project, remaining=10)
        self.assertEqual(throughput, 2.0)

    def test_zero_remaining_yields_zero_throughput(self):
        self.assertEqual(auto_throughput(self.project, remaining=0), 0.0)


class DeficitPickerTests(TestCase):
    def setUp(self):
        set_distribution_mode(PlatformConfig.MANUAL)
        self.user = make_user("picker")
        self.project_a = make_project("Heavy", slug="heavy", serving_weight=80)
        self.project_b = make_project("Light", slug="light", serving_weight=20)
        self.task_a = make_task(self.project_a, task_id="heavy-1", complexity=1)
        self.task_b = make_task(self.project_b, task_id="light-1", complexity=1)
        self.eligible = scoped_tasks_queryset(active_only=True).filter(complexity=1)

    def test_favors_under_served_project(self):
        WorkerAnswer.objects.create(
            user=self.user,
            task=self.task_a,
            selected_answer="a",
            is_correct=True,
            verified=True,
        )
        for index in range(4):
            task = make_task(self.project_a, task_id=f"heavy-extra-{index}", complexity=1)
            WorkerAnswer.objects.create(
                user=self.user,
                task=task,
                selected_answer="a",
                is_correct=True,
                verified=True,
            )
        eligible = scoped_tasks_queryset(active_only=True).filter(complexity=1)
        eligible = eligible.exclude(
            id__in=WorkerAnswer.objects.filter(user=self.user).values_list("task_id", flat=True)
        )
        picked = pick_task_by_project_deficit(self.user, eligible)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.project_id, self.project_b.id)

    @patch("core.distribution.random.choice")
    def test_returns_none_when_no_weights(self, mock_choice):
        self.project_a.serving_weight = 0
        self.project_a.save()
        self.project_b.serving_weight = 0
        self.project_b.save()
        picked = pick_task_by_project_deficit(self.user, self.eligible)
        self.assertIsNone(picked)
        mock_choice.assert_not_called()


class RemainingTaskCountTests(TestCase):
    def setUp(self):
        self.project = make_project("Remain", slug="remain")
        self.task = make_task(
            self.project,
            task_id="remain-1",
            is_goldtask=False,
            correct_answer=None,
        )

    def test_counts_tasks_below_target_coverage(self):
        self.assertEqual(remaining_task_count(self.project), 1)
        for index in range(3):
            worker = make_user(f"answerer{index}")
            WorkerAnswer.objects.create(
                user=worker,
                task=self.task,
                selected_answer="a",
                is_correct=None,
                verified=False,
            )
        self.assertEqual(remaining_task_count(self.project), 0)
