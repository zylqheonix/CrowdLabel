"""Live admin analytics — task throughput and worker accuracy/activity."""

from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone

from .models import User, WorkerAnswer
from .projects import project_scope_context, resolve_project_scope, scoped_answers_queryset, scoped_tasks_queryset
from .review_queue import build_review_queue

TASK_DIMENSIONS = {
    "category": ("category", "Category"),
    "topic": ("region_tag", "Topic"),
    "complexity": ("complexity", "Complexity"),
    "type": ("format", "Type"),
}

COMPLEXITY_LABELS = {
    1: "Easy (1)",
    2: "Medium (2)",
    3: "Medium (3)",
    4: "Hard (4)",
}

ACCURACY_BUCKET_DEFS = [
    (0, 20, "0–19%"),
    (20, 40, "20–39%"),
    (40, 60, "40–59%"),
    (60, 80, "60–79%"),
    (80, 101, "80–100%"),
]

COVERAGE_BUCKETS = [
    ("0", lambda n: n == 0),
    ("1", lambda n: n == 1),
    ("2", lambda n: n == 2),
    ("3+", lambda n: n >= 3),
]


def _to_int(raw, default):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _as_local_date(value):
    if value is None:
        return None
    if hasattr(value, "utcoffset"):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    return value


def _format_week_label(period_start):
    """Compact axis label + full range for tooltip (Mon–Sun bucket)."""
    start = _as_local_date(period_start)
    if not start:
        return "—", ""
    end = start + timedelta(days=6)
    title = f"Week of {start.strftime('%a %b %d')} – {end.strftime('%a %b %d, %Y')}"
    if start.month == end.month:
        label = f"{start.strftime('%b %d')}–{end.strftime('%d, %Y')}"
    else:
        label = f"{start.strftime('%b %d')}–{end.strftime('%b %d, %Y')}"
    return label, title


def _format_day_label(day):
    d = _as_local_date(day)
    if not d:
        return "—", ""
    return d.strftime("%b %d, %Y"), d.strftime("%A, %B %d, %Y")


def _bars_from_counts(labeled_counts, max_bars=None):
    """Turn [(label, count)] or [(label, count, title), ...] into bar chart rows."""
    items = list(labeled_counts)
    if max_bars:
        items = items[:max_bars]
    peak = max((item[1] for item in items), default=0)
    bars = []
    for item in items:
        label, count = item[0], item[1]
        title = item[2] if len(item) > 2 else ""
        pct = int(round((count / peak) * 100)) if peak else 0
        bars.append(
            {
                "label": label,
                "count": count,
                "pct": max(pct, 4 if count else 0),
                "title": title,
            }
        )
    return bars


def _task_status_breakdown(project_id):
    """Derived coverage status — Task has no status field."""
    low = settings.REVIEW_LOW_COVERAGE
    annotated = scoped_tasks_queryset(project_id).annotate(answer_count=Count("answers"))
    unanswered = annotated.filter(answer_count=0).count()
    thin = annotated.filter(answer_count__gte=1, answer_count__lt=low).count()
    adequate = annotated.filter(answer_count__gte=low).count()
    return [
        {"label": "No answers yet", "count": unanswered, "hint": "0 worker submissions"},
        {
            "label": f"Thin coverage (1–{low - 1})",
            "count": thin,
            "hint": f"Below {low} answers (review-queue low-coverage threshold)",
        },
        {
            "label": f"Adequate coverage ({low}+)",
            "count": adequate,
            "hint": f"At least {low} answers",
        },
    ]


def _volume_by_dimension(dimension_key, project_id):
    field_name, _ = TASK_DIMENSIONS[dimension_key]
    base_qs = scoped_tasks_queryset(project_id)
    if field_name == "complexity":
        rows = base_qs.values("complexity").annotate(count=Count("id")).order_by("complexity")
        labeled = []
        for row in rows:
            complexity = row["complexity"]
            if complexity is None:
                label = "Unset"
            else:
                label = COMPLEXITY_LABELS.get(complexity, str(complexity))
            labeled.append((label, row["count"]))
        return labeled

    rows = (
        base_qs.values(field_name)
        .annotate(count=Count("id"))
        .order_by("-count", field_name)
    )
    labeled = []
    for row in rows:
        raw = row[field_name]
        label = str(raw) if raw not in (None, "") else "Unset"
        labeled.append((label, row["count"]))
    return labeled


def _complexity_distribution(project_id):
    base_qs = scoped_tasks_queryset(project_id)
    counts = Counter(
        base_qs.exclude(complexity__isnull=True).values_list("complexity", flat=True)
    )
    unset = base_qs.filter(complexity__isnull=True).count()
    rows = []
    for level in sorted(counts):
        rows.append((COMPLEXITY_LABELS.get(level, str(level)), counts[level]))
    if unset:
        rows.append(("Unset", unset))
    return rows


def _coverage_distribution(project_id):
    answer_counts = Counter(
        scoped_tasks_queryset(project_id)
        .annotate(ac=Count("answers"))
        .values_list("ac", flat=True)
    )
    buckets = []
    for label, predicate in COVERAGE_BUCKETS:
        count = sum(c for n, c in answer_counts.items() if predicate(n))
        buckets.append((label, count))
    return buckets


def _gold_pass_by_complexity(project_id):
    rows = (
        scoped_answers_queryset(project_id)
        .filter(task__is_goldtask=True, is_correct__isnull=False)
        .values("task__complexity")
        .annotate(
            total=Count("id"),
            correct=Count("id", filter=Q(is_correct=True)),
        )
        .order_by("task__complexity")
    )
    result = []
    for row in rows:
        complexity = row["task__complexity"]
        total = row["total"]
        correct = row["correct"]
        label = (
            COMPLEXITY_LABELS.get(complexity, str(complexity))
            if complexity is not None
            else "Unset"
        )
        rate = (correct / total * 100) if total else None
        result.append(
            {
                "label": label,
                "total": total,
                "correct": correct,
                "rate_pct": round(rate, 1) if rate is not None else None,
            }
        )
    return result


def _worker_stats(active_days, project_id):
    answer_qs = scoped_answers_queryset(project_id)
    worker_ids_with_answers = set(
        answer_qs.filter(user__role=User.WORKER).values_list("user_id", flat=True)
    )
    total_workers = User.objects.filter(role=User.WORKER).count()
    cutoff = timezone.now() - timedelta(days=active_days)
    active_workers = len(
        set(
            answer_qs.filter(created_at__gte=cutoff).values_list("user_id", flat=True)
        )
    )

    per_worker_tasks = (
        answer_qs.filter(user__role=User.WORKER)
        .values("user_id")
        .annotate(task_count=Count("task", distinct=True))
    )
    task_counts = [row["task_count"] for row in per_worker_tasks]
    avg_tasks = round(sum(task_counts) / len(task_counts), 1) if task_counts else 0

    return {
        "total_workers": total_workers,
        "active_workers": active_workers,
        "active_days": active_days,
        "avg_tasks_per_worker": avg_tasks,
        "workers_with_answers": len(worker_ids_with_answers),
    }


def _worker_accuracy_distribution(project_id):
    min_volume = settings.ANALYTICS_MIN_WORKER_VOLUME
    answer_qs = scoped_answers_queryset(project_id)
    worker_ids = (
        answer_qs.filter(user__role=User.WORKER, is_correct__isnull=False)
        .values_list("user_id", flat=True)
        .distinct()
    )
    workers = User.objects.filter(id__in=worker_ids).order_by("id")
    accuracies = []
    bucket_counts = Counter()

    for worker in workers:
        stats = answer_qs.filter(user=worker, is_correct__isnull=False).aggregate(
            total=Count("id"),
            correct=Count("id", filter=Q(is_correct=True)),
        )
        total = stats["total"] or 0
        if total == 0:
            continue
        pct = stats["correct"] / total * 100
        accuracies.append({"user_id": worker.id, "pct": pct, "total": total})
        placed = False
        for low, high, label in ACCURACY_BUCKET_DEFS:
            if low <= pct < high:
                bucket_counts[label] += 1
                placed = True
                break
        if not placed:
            bucket_counts["80–100%"] += 1

    meaningful = [a for a in accuracies if a["total"] >= min_volume]
    return {
        "buckets": [(label, bucket_counts.get(label, 0)) for label, _, _ in ACCURACY_BUCKET_DEFS]
        + [("No verified answers", bucket_counts.get("No verified answers", 0))],
        "workers_with_verified": len(accuracies),
        "workers_meaningful": len(meaningful),
        "min_volume": min_volume,
        "low_sample_warning": len(meaningful) < 3,
    }


def _activity_over_time(granularity, project_id, days_back=90):
    cutoff = timezone.now() - timedelta(days=days_back)
    qs = scoped_answers_queryset(project_id).filter(created_at__gte=cutoff)
    if granularity == "week":
        rows = (
            qs.annotate(period=TruncWeek("created_at"))
            .values("period")
            .annotate(count=Count("id"))
            .order_by("period")
        )
        labeled = []
        for row in rows:
            label, title = _format_week_label(row["period"])
            labeled.append((label, row["count"], title))
    else:
        rows = (
            qs.annotate(period=TruncDate("created_at"))
            .values("period")
            .annotate(count=Count("id"))
            .order_by("period")
        )
        labeled = []
        for row in rows:
            label, title = _format_day_label(row["period"])
            labeled.append((label, row["count"], title))
    return labeled


def _answers_by_complexity(project_id):
    rows = (
        scoped_answers_queryset(project_id)
        .exclude(task__complexity__isnull=True)
        .values("task__complexity")
        .annotate(count=Count("id"))
        .order_by("task__complexity")
    )
    return [
        (
            COMPLEXITY_LABELS.get(row["task__complexity"], str(row["task__complexity"])),
            row["count"],
        )
        for row in rows
    ]


def _worker_volume_table(worker_order, project_id):
    answer_qs = scoped_answers_queryset(project_id)
    worker_ids = (
        answer_qs.filter(user__role=User.WORKER)
        .values_list("user_id", flat=True)
        .distinct()
    )
    rows = []
    for worker in User.objects.filter(id__in=worker_ids).order_by("username"):
        stats = answer_qs.filter(user=worker).aggregate(
            answer_count=Count("id"),
            task_count=Count("task", distinct=True),
            verified_total=Count("id", filter=Q(is_correct__isnull=False)),
            verified_correct=Count("id", filter=Q(is_correct=True)),
        )
        task_count = stats["task_count"] or 0
        verified_total = stats["verified_total"] or 0
        if verified_total:
            accuracy_pct = stats["verified_correct"] / verified_total * 100
            accuracy_display = f"{accuracy_pct:.0f}%"
        else:
            accuracy_pct = None
            accuracy_display = "—"
        rows.append(
            {
                "username": worker.username,
                "task_count": task_count,
                "answer_count": stats["answer_count"] or 0,
                "accuracy_display": accuracy_display,
                "_accuracy": accuracy_pct if accuracy_pct is not None else -1,
            }
        )

    if worker_order == "volume_asc":
        rows.sort(key=lambda r: (r["task_count"], r["username"]))
    elif worker_order == "accuracy_desc":
        rows.sort(key=lambda r: (r["_accuracy"], r["task_count"]), reverse=True)
    elif worker_order == "accuracy_asc":
        rows.sort(key=lambda r: (r["_accuracy"] if r["_accuracy"] >= 0 else 999, r["task_count"]))
    else:
        rows.sort(key=lambda r: (-r["task_count"], r["username"]))
    return rows


def build_admin_analytics(request_get):
    project_id, selected_project, _ = resolve_project_scope(request_get)
    scope = project_scope_context(request_get)

    task_dimension = request_get.get("task_dimension", "category").strip()
    if task_dimension not in TASK_DIMENSIONS:
        task_dimension = "category"

    active_days = _to_int(
        request_get.get("active_days"), settings.ANALYTICS_ACTIVE_DAYS_DEFAULT
    )
    if active_days not in (7, 30):
        active_days = settings.ANALYTICS_ACTIVE_DAYS_DEFAULT

    activity_granularity = request_get.get("activity_granularity", "day").strip()
    if activity_granularity not in ("day", "week"):
        activity_granularity = "day"

    worker_order = request_get.get("worker_order", "volume_desc").strip()
    if worker_order not in ("volume_desc", "volume_asc", "accuracy_desc", "accuracy_asc"):
        worker_order = "volume_desc"

    tasks_qs = scoped_tasks_queryset(project_id)
    total_tasks = tasks_qs.count()
    gold_tasks = tasks_qs.filter(is_goldtask=True).count()

    _, review_summary, _, _ = build_review_queue(request_get)

    volume_counts = _volume_by_dimension(task_dimension, project_id)
    coverage_counts = _coverage_distribution(project_id)
    accuracy_dist = _worker_accuracy_distribution(project_id)
    activity_counts = _activity_over_time(activity_granularity, project_id)

    return {
        **scope,
        "task_kpis": {
            "total_tasks": total_tasks,
            "gold_tasks": gold_tasks,
            "gold_pct": round(gold_tasks / total_tasks * 100, 1) if total_tasks else None,
            "status_rows": _task_status_breakdown(project_id),
            "attention_count": review_summary["total_flagged"],
        },
        "task_dimension": task_dimension,
        "task_dimension_label": TASK_DIMENSIONS[task_dimension][1],
        "volume_bars": _bars_from_counts(volume_counts, max_bars=12),
        "complexity_bars": _bars_from_counts(_complexity_distribution(project_id)),
        "coverage_bars": _bars_from_counts(coverage_counts),
        "gold_pass_rows": _gold_pass_by_complexity(project_id),
        "worker_kpis": _worker_stats(active_days, project_id),
        "accuracy_bars": _bars_from_counts(accuracy_dist["buckets"]),
        "accuracy_meta": accuracy_dist,
        "activity_granularity": activity_granularity,
        "activity_bars": _bars_from_counts(activity_counts, max_bars=30),
        "complexity_answer_bars": _bars_from_counts(_answers_by_complexity(project_id)),
        "worker_rows": _worker_volume_table(worker_order, project_id),
        "worker_order": worker_order,
        "selected": {
            "project": selected_project,
            "task_dimension": task_dimension,
            "active_days": active_days,
            "activity_granularity": activity_granularity,
            "worker_order": worker_order,
        },
    }
