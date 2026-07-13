"""Points balance and single-answer-per-task semantics."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import WorkerAnswer
from core.points import calculate_points, get_balance, spend_points

from .helpers import make_project, make_task, make_user


class PointsCalculationTests(TestCase):
    def setUp(self):
        self.user = make_user("pointuser")
        self.project = make_project("Points", slug="points")
        self.easy = make_task(self.project, task_id="easy-1", complexity=1, correct_answer="a")
        self.hard = make_task(self.project, task_id="hard-1", complexity=4, correct_answer="a")

    def test_completion_and_correctness_points(self):
        WorkerAnswer.objects.create(
            user=self.user,
            task=self.easy,
            selected_answer="a",
            is_correct=True,
            verified=True,
        )
        WorkerAnswer.objects.create(
            user=self.user,
            task=self.hard,
            selected_answer="a",
            is_correct=True,
            verified=True,
        )
        # 2 tasks * 5 completion + 5 easy bonus + 15 hard bonus = 30
        self.assertEqual(calculate_points(self.user), 30)

    def test_spend_reduces_balance(self):
        WorkerAnswer.objects.create(
            user=self.user,
            task=self.easy,
            selected_answer="a",
            is_correct=True,
            verified=True,
        )
        spend_points(self.user, 7, "test purchase")
        self.assertEqual(get_balance(self.user), 3)


class UniqueAnswerConstraintTests(TestCase):
    def setUp(self):
        self.user = make_user("appenduser")
        self.project = make_project("Append", slug="append")
        self.task = make_task(self.project, task_id="append-1")

    def test_duplicate_answer_rows_are_rejected(self):
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
        self.assertEqual(WorkerAnswer.objects.filter(user=self.user, task=self.task).count(), 1)
