import ast
import csv
import json
from collections import Counter, defaultdict
from functools import lru_cache

from django.conf import settings
from django.db.models import Count

from .models import Task, WorkerAnswer
from .projects import resolve_project_scope, scoped_tasks_queryset

FLAG_CROWD_VS_TRUTH = "crowd_vs_truth"
FLAG_CROWD_DISAGREEMENT = "crowd_disagreement"
FLAG_GOLD_FAILURE = "gold_failure"
FLAG_ORDER = [
    FLAG_CROWD_VS_TRUTH,
    FLAG_CROWD_DISAGREEMENT,
    FLAG_GOLD_FAILURE,
]


def _to_int(raw, default=None):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _to_int_set(raw_values):
    values = set()
    for raw in raw_values:
        parsed = _to_int(raw)
        if parsed is not None:
            values.add(parsed)
    return values


def _build_distribution_map(task_ids):
    rows = WorkerAnswer.objects.filter(task_id__in=task_ids).values(
        "task_id", "selected_answer"
    ).annotate(c=Count("id"))
    distribution_by_task = defaultdict(dict)
    for row in rows:
        key = row["selected_answer"] or "—"
        distribution_by_task[row["task_id"]][key] = row["c"]
    return distribution_by_task


def _majority_info(distribution):
    if not distribution:
        return None, 0, True
    ordered = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    top_count = ordered[0][1]
    tied = [choice for choice, count in ordered if count == top_count]
    if len(tied) > 1:
        return None, top_count, True
    return ordered[0][0], top_count, False


def _distribution_label(distribution):
    if not distribution:
        return "—"
    return ", ".join(f"{choice}:{count}" for choice, count in sorted(distribution.items()))


def _compute_task_row(task, distribution):
    answer_count = sum(distribution.values())
    majority, majority_count, is_tie = _majority_info(distribution)
    if answer_count < 2:
        agreement = None
    else:
        agreement = 0.0 if is_tie else (majority_count / answer_count)
    ground_truth = task.ground_truth

    if answer_count == 0:
        crowd_correct = None
    elif is_tie or not ground_truth:
        crowd_correct = False
    else:
        crowd_correct = majority == ground_truth

    gold_accuracy = None
    if answer_count and ground_truth:
        gold_accuracy = distribution.get(ground_truth, 0) / answer_count

    flags = []
    if answer_count >= 1 and ground_truth and (is_tie or majority != ground_truth):
        flags.append(FLAG_CROWD_VS_TRUTH)
    if answer_count >= 2 and agreement < settings.REVIEW_AGREEMENT_THRESHOLD:
        flags.append(FLAG_CROWD_DISAGREEMENT)
    if (
        task.is_goldtask
        and gold_accuracy is not None
        and gold_accuracy < settings.REVIEW_GOLD_FAIL_THRESHOLD
    ):
        flags.append(FLAG_GOLD_FAILURE)
    resolved_answer = task.admin_resolved_answer if not task.is_goldtask else None
    resolved_answer_label = (
        (task.choices or {}).get(resolved_answer, resolved_answer) if resolved_answer else None
    )
    return {
        "pk": task.pk,
        "task_id": task.task_id,
        "image": task.image,
        "question": task.task,
        "category": task.category or "—",
        "topic": task.region_tag or "—",
        "type": task.format or "—",
        "complexity": task.complexity if task.complexity is not None else "—",
        "ground_truth": ground_truth or "—",
        "distribution": _distribution_label(distribution),
        "distribution_map": distribution,
        "answer_count": answer_count,
        "agreement": agreement,
        "agreement_pct": int(round(agreement * 100)) if agreement is not None else None,
        "crowd_correct": crowd_correct,
        "majority": "tie" if is_tie else (majority or "—"),
        "flags": flags,
        "flag_reason": "; ".join(flags) if flags else "—",
        "is_goldtask": task.is_goldtask,
        "low_coverage": answer_count < settings.REVIEW_LOW_COVERAGE,
        "is_resolved": bool(resolved_answer),
        "resolved_answer": resolved_answer,
        "resolved_answer_label": resolved_answer_label,
        "resolved_by": getattr(task.resolved_by, "username", None),
        "resolved_at": task.resolved_at,
    }


def build_resolve_context(task):
    """Shared per-task review context using existing crowd helpers."""
    distribution = _build_distribution_map([task.id]).get(task.id, {})
    answer_count = sum(distribution.values())
    majority, majority_count, is_tie = _majority_info(distribution)
    if answer_count < 2:
        agreement = None
    else:
        agreement = 0.0 if is_tie else (majority_count / answer_count)

    sample_row = _sample_task_row(task.task_id)
    parsed_choices = _parse_choices(sample_row.get("choices", "")) if sample_row else {}
    choice_map = parsed_choices if parsed_choices else (task.choices or {})

    # Ensure all observed votes are represented even if absent from choices.
    ordered_keys = sorted(set(choice_map.keys()) | set(distribution.keys()))
    crowd_rows = []
    for key in ordered_keys:
        count = distribution.get(key, 0)
        pct = (count / answer_count * 100) if answer_count else 0.0
        crowd_rows.append(
            {
                "key": key,
                "label": choice_map.get(key, key),
                "count": count,
                "pct": round(pct, 1),
            }
        )

    llm_stats = None
    submitted_answer = None
    if sample_row:
        submitted_answer = (sample_row.get("submitted_answer") or "").strip() or None
        llm_answer = (sample_row.get("llm_answer") or "").strip() or None
        info = _parse_llm_info(sample_row.get("llm_info") or "")
        probs = info.get("probs") if isinstance(info.get("probs"), dict) else {}
        if llm_answer:
            llm_stats = {
                "answer_key": llm_answer,
                "answer_label": choice_map.get(llm_answer, llm_answer),
                "confidence": probs.get(llm_answer),
                "probs": probs,
            }

    ground_truth = task.correct_answer if task.is_goldtask else submitted_answer
    return {
        "distribution_map": distribution,
        "coverage": answer_count,
        "majority": "tie" if is_tie else (majority or "—"),
        "agreement_pct": int(round(agreement * 100)) if agreement is not None else None,
        "crowd_rows": crowd_rows,
        "choice_map": choice_map,
        "llm_stats": llm_stats,
        "ground_truth": ground_truth,
    }


@lru_cache(maxsize=1)
def _sample_task_rows():
    """Load tasks_table.csv rows once for non-gold resolve metadata."""
    path = settings.BASE_DIR / "sample_data" / "tasks_table.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return {str(row.get("task_id", "")).strip(): row for row in reader}


def _sample_task_row(task_id):
    return _sample_task_rows().get(str(task_id).strip())


def _parse_llm_info(raw):
    """llm_info is JSON string in pipeline exports."""
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (TypeError, ValueError):
        return {}


def _parse_choices(raw):
    """choices is Python-literal dict string in pipeline exports."""
    try:
        val = ast.literal_eval(raw)
        return val if isinstance(val, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def build_review_queue(request_get):
    project_id, selected_project, _ = resolve_project_scope(request_get)
    tasks_qs = scoped_tasks_queryset(project_id)

    # Task-level filters.
    category = request_get.get("category", "").strip()
    topics = [value.strip() for value in request_get.getlist("topic") if value.strip()]
    kind = request_get.get("type", "").strip()
    complexities = _to_int_set(request_get.getlist("complexity"))
    gold_filter = request_get.get("gold", "").strip()
    resolution_filter = request_get.get("resolution", "").strip()
    min_coverage = _to_int(request_get.get("min_coverage"), default=0)
    flag_filters = [value.strip() for value in request_get.getlist("flag") if value.strip()]
    sort_key = request_get.get("sort", "agreement").strip()

    if category:
        tasks_qs = tasks_qs.filter(category=category)
    if topics:
        tasks_qs = tasks_qs.filter(region_tag__in=topics)
    if kind:
        tasks_qs = tasks_qs.filter(format=kind)
    if complexities:
        tasks_qs = tasks_qs.filter(complexity__in=complexities)
    if gold_filter == "gold":
        tasks_qs = tasks_qs.filter(is_goldtask=True)
    elif gold_filter == "regular":
        tasks_qs = tasks_qs.filter(is_goldtask=False)

    tasks = list(tasks_qs)
    task_ids = [task.id for task in tasks]
    distribution_by_task = _build_distribution_map(task_ids) if task_ids else {}
    rows = [
        _compute_task_row(task, distribution_by_task.get(task.id, {}))
        for task in tasks
    ]

    # Computed filters.
    if min_coverage:
        rows = [row for row in rows if row["answer_count"] >= min_coverage]
    if flag_filters:
        rows = [
            row
            for row in rows
            if any(flag in row["flags"] for flag in flag_filters)
        ]
    if resolution_filter == "resolved":
        rows = [row for row in rows if row["is_resolved"]]
    elif resolution_filter == "unresolved":
        rows = [row for row in rows if (not row["is_resolved"] and not row["is_goldtask"])]

    # Sorting.
    if sort_key == "answer_count":
        rows.sort(key=lambda row: (-row["answer_count"], row["task_id"]))
    elif sort_key == "complexity":
        rows.sort(
            key=lambda row: (
                row["complexity"] if isinstance(row["complexity"], int) else -1,
                row["task_id"],
            )
        )
    else:
        # Default worst-first: lowest agreement first.
        rows.sort(
            key=lambda row: (
                row["agreement"] is None,
                row["agreement"] if row["agreement"] is not None else 0,
                -row["answer_count"],
                row["task_id"],
            )
        )
        sort_key = "agreement"

    summary_counts = Counter()
    for row in rows:
        for reason in row["flags"]:
            summary_counts[reason] += 1

    filter_options = {
        "categories": list(
            tasks_qs.exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        ),
        "topics": list(
            tasks_qs.exclude(region_tag="")
            .values_list("region_tag", flat=True)
            .distinct()
            .order_by("region_tag")
        ),
        "types": list(
            tasks_qs.exclude(format="")
            .values_list("format", flat=True)
            .distinct()
            .order_by("format")
        ),
        "complexities": list(
            tasks_qs.exclude(complexity__isnull=True)
            .values_list("complexity", flat=True)
            .distinct()
            .order_by("complexity")
        ),
    }

    selected = {
        "project": selected_project,
        "category": category,
        "topics": topics,
        "type": kind,
        "complexities": sorted(complexities),
        "gold": gold_filter,
        "resolution": resolution_filter,
        "min_coverage": min_coverage if min_coverage else "",
        "flags": flag_filters,
        "sort": sort_key,
    }

    summary = {
        "total_tasks": len(rows),
        "total_flagged": sum(1 for row in rows if row["flags"]),
        "flag_counts": {flag: summary_counts.get(flag, 0) for flag in FLAG_ORDER},
    }
    return rows, summary, selected, filter_options
