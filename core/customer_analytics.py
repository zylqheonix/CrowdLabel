"""Task-level analytics for customer project views — no worker or gold metrics."""

from django.db.models import Count

from .analytics import (
    TASK_DIMENSIONS,
    _activity_over_time,
    _answers_by_complexity,
    _bars_from_counts,
    _complexity_distribution,
    _coverage_distribution,
    _task_status_breakdown,
    _volume_by_dimension,
)
from .models import Project, Task


def project_progress(project):
    """Percent of tasks with at least one worker answer."""
    total = project.tasks.count()
    if not total:
        return {"total": 0, "answered": 0, "progress_pct": 0}
    answered = (
        project.tasks.annotate(answer_count=Count("answers"))
        .filter(answer_count__gte=1)
        .count()
    )
    return {
        "total": total,
        "answered": answered,
        "progress_pct": int(round((answered / total) * 100)),
    }


def build_customer_project_analytics(project):
    """Live task analytics scoped to one project — customer-safe subset."""
    project_id = project.id
    progress = project_progress(project)
    volume_dimension = "category"

    return {
        "project": project,
        "progress": progress,
        "status_rows": _task_status_breakdown(project_id),
        "volume_bars": _bars_from_counts(
            _volume_by_dimension(volume_dimension, project_id), max_bars=12
        ),
        "volume_dimension": TASK_DIMENSIONS[volume_dimension][1],
        "complexity_bars": _bars_from_counts(_complexity_distribution(project_id)),
        "coverage_bars": _bars_from_counts(_coverage_distribution(project_id)),
        "activity_rows": _bars_from_counts(_activity_over_time("week", project_id), max_bars=30),
        "answers_by_complexity": _bars_from_counts(_answers_by_complexity(project_id)),
    }


def customer_dashboard_rows(user):
    """Project list rows for a customer dashboard."""
    rows = []
    for project in Project.objects.filter(owner=user).order_by("-created_at"):
        progress = project_progress(project)
        rows.append(
            {
                "project": project,
                "progress": progress,
            }
        )
    return rows
