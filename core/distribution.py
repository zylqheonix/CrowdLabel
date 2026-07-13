"""Project question distribution — manual/auto weights and deficit-based serving."""

import random

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import PlatformConfig, Project, WorkerAnswer
from .projects import scoped_tasks_queryset


def get_distribution_mode():
    return PlatformConfig.load().distribution_mode


def remaining_task_count(project):
    """Non-gold tasks in project with answer count below TARGET_COVERAGE."""
    return (
        scoped_tasks_queryset(active_only=True)
        .filter(project=project, is_goldtask=False)
        .annotate(answer_count=Count("answers"))
        .filter(answer_count__lt=settings.TARGET_COVERAGE)
        .count()
    )


def auto_throughput(project, remaining):
    if remaining == 0:
        return 0.0
    if project.deadline is None:
        return float(settings.NO_DEADLINE_URGENCY)
    days_left = (project.deadline - timezone.localdate()).days
    effective_days = max(float(days_left), float(settings.MIN_DAYS_FLOOR))
    return remaining / effective_days


def compute_project_weights():
    """Return {project: weight} for active projects with weight > 0."""
    mode = get_distribution_mode()
    active_projects = list(
        Project.objects.filter(is_active=True, status=Project.ACTIVE)
    )

    if mode == PlatformConfig.MANUAL:
        return {
            project: float(project.serving_weight)
            for project in active_projects
            if project.serving_weight > 0
        }

    weights = {}
    for project in active_projects:
        remaining = remaining_task_count(project)
        if remaining == 0:
            continue
        throughput = auto_throughput(project, remaining)
        weight = throughput * float(project.serving_boost)
        if weight > 0:
            weights[project] = weight
    return weights


def _non_gold_answered_by_project(user, project_ids):
    rows = (
        WorkerAnswer.objects.filter(
            user=user,
            task__project_id__in=project_ids,
            task__is_goldtask=False,
        )
        .values("task__project_id")
        .annotate(c=Count("id"))
    )
    return {row["task__project_id"]: row["c"] for row in rows}


def pick_task_by_project_deficit(user, eligible_queryset):
    """Pick one task from eligible pool using deficit-based project weights.

    Returns None when weighting does not apply — caller falls back to un-weighted
    selection so workers never dead-end while eligible tasks exist elsewhere.
    """
    weights = compute_project_weights()
    if not weights:
        return None

    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        return None

    fractions = {project: weight / weight_sum for project, weight in weights.items()}
    project_ids = [project.id for project in weights]

    eligible_project_ids = set(
        eligible_queryset.filter(project_id__in=project_ids)
        .values_list("project_id", flat=True)
        .distinct()
    )
    if not eligible_project_ids:
        return None

    answered_by_project = _non_gold_answered_by_project(user, project_ids)
    n = sum(answered_by_project.get(project.id, 0) for project in weights)

    best_deficit = None
    best_projects = []

    for project, fraction in fractions.items():
        if project.id not in eligible_project_ids:
            continue
        answered_p = answered_by_project.get(project.id, 0)
        deficit = fraction * (n + 1) - answered_p

        if best_deficit is None or deficit > best_deficit:
            best_deficit = deficit
            best_projects = [project]
        elif deficit == best_deficit:
            best_projects.append(project)

    if not best_projects:
        return None

    max_weight = max(weights[project] for project in best_projects)
    tied = [project for project in best_projects if weights[project] == max_weight]
    chosen_project = random.choice(tied)

    return eligible_queryset.filter(project_id=chosen_project.id).first()


def build_distribution_page_context():
    """Context for the admin question-distribution page."""
    mode = get_distribution_mode()
    active_projects = list(
        Project.objects.filter(is_active=True, status=Project.ACTIVE).order_by("name")
    )

    rows = []
    manual_weight_sum = 0
    auto_final_sum = 0.0

    for project in active_projects:
        remaining = remaining_task_count(project)
        throughput = auto_throughput(project, remaining)
        final_auto = throughput * float(project.serving_boost)
        manual_weight_sum += project.serving_weight
        if final_auto > 0:
            auto_final_sum += final_auto

        rows.append(
            {
                "project": project,
                "remaining": remaining,
                "days_left": project.days_until_deadline,
                "throughput": throughput,
                "final_auto_weight": final_auto,
            }
        )

    for row in rows:
        project = row["project"]
        if mode == PlatformConfig.MANUAL:
            weight = project.serving_weight
            row["normalized_pct"] = (
                round(weight / manual_weight_sum * 100, 1) if manual_weight_sum and weight > 0 else None
            )
        else:
            final = row["final_auto_weight"]
            row["normalized_pct"] = (
                round(final / auto_final_sum * 100, 1) if auto_final_sum and final > 0 else None
            )

    return {
        "distribution_mode": mode,
        "is_manual": mode == PlatformConfig.MANUAL,
        "is_auto": mode == PlatformConfig.AUTO,
        "project_rows": rows,
        "manual_weight_sum": manual_weight_sum,
        "manual_weights_relative": manual_weight_sum != 100 and manual_weight_sum > 0,
    }
