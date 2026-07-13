import calendar
from datetime import date, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .models import WorkerAnswer

ACTIVITY_BUCKET_1_MAX = 2
ACTIVITY_BUCKET_2_MAX = 5
ACTIVITY_BUCKET_3_MAX = 9
ACTIVITY_DAYS = 365

DIFFICULTY_SECTIONS = [
    ("easy", _("Easy"), {1}),
    ("medium", _("Medium"), {2, 3}),
    ("hard", _("Hard"), {4}),
]


def _difficulty_key(complexity):
    if complexity == 1:
        return "easy"
    if complexity in (2, 3):
        return "medium"
    if complexity == 4:
        return "hard"
    return None


def _latest_answers_by_task(user):
    latest = {}
    answers = (
        WorkerAnswer.objects.filter(user=user)
        .select_related("task")
        .order_by("task_id", "-created_at")
    )
    for answer in answers:
        if answer.task_id not in latest:
            latest[answer.task_id] = answer
    return latest


def _cell_from_answer(answer):
    if answer.is_correct is True:
        status = "correct"
        label = gettext("Correct")
    elif answer.is_correct is False:
        status = "incorrect"
        label = gettext("Incorrect")
    else:
        status = "unscored"
        label = gettext("Unscored")
    return {
        "task_id": answer.task.task_id,
        "status": status,
        "title": gettext("%(task_id)s — %(label)s") % {
            "task_id": answer.task.task_id,
            "label": label,
        },
    }


def _section_summary(cells):
    answered = len(cells)
    correct = sum(1 for cell in cells if cell["status"] == "correct")
    verified = sum(1 for cell in cells if cell["status"] in ("correct", "incorrect"))
    percent = int((correct / verified) * 100) if verified else None
    return {
        "answered": answered,
        "correct": correct,
        "percent": percent,
    }


def answer_history_sections(user):
    latest = _latest_answers_by_task(user)
    sections = []

    for key, label, complexities in DIFFICULTY_SECTIONS:
        cells = []
        for answer in sorted(
            (a for a in latest.values() if a.task.complexity in complexities),
            key=lambda row: row.task_id,
        ):
            cells.append(_cell_from_answer(answer))

        summary = _section_summary(cells)
        sections.append(
            {
                "key": key,
                "label": label,
                "cells": cells,
                "summary": summary,
                "empty": not cells,
            }
        )
    return sections


def _activity_level(count):
    if count <= 0:
        return 0
    if count <= ACTIVITY_BUCKET_1_MAX:
        return 1
    if count <= ACTIVITY_BUCKET_2_MAX:
        return 2
    if count <= ACTIVITY_BUCKET_3_MAX:
        return 3
    return 4


def _month_start(day):
    return day.replace(day=1)


def _next_month(month_start):
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def _previous_month(month_start):
    if month_start.month == 1:
        return date(month_start.year - 1, 12, 1)
    return date(month_start.year, month_start.month - 1, 1)


def _resolve_month_start(month_raw, earliest_month, latest_month):
    if month_raw:
        try:
            year, month = month_raw.split("-", 1)
            resolved = date(int(year), int(month), 1)
        except (TypeError, ValueError):
            resolved = latest_month
    else:
        resolved = latest_month
    if resolved < earliest_month:
        return earliest_month
    if resolved > latest_month:
        return latest_month
    return resolved


def activity_calendar(user, month_raw=None):
    today = timezone.localdate()
    range_start = today - timedelta(days=ACTIVITY_DAYS - 1)
    earliest_month = _month_start(range_start)
    latest_month = _month_start(today)
    month_start = _resolve_month_start(month_raw, earliest_month, latest_month)
    month_end = _next_month(month_start) - timedelta(days=1)
    query_start = max(range_start, month_start)
    query_end = min(today, month_end)
    tz = timezone.get_current_timezone()

    daily_counts = {}
    if query_start <= query_end:
        daily_counts = {
            row["day"]: row["count"]
            for row in (
                WorkerAnswer.objects.filter(
                    user=user,
                    created_at__date__gte=query_start,
                    created_at__date__lte=query_end,
                )
                .annotate(day=TruncDate("created_at", tzinfo=tz))
                .values("day")
                .annotate(count=Count("id"))
            )
        }

    weeks = []
    active_days = 0
    month_weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
        month_start.year, month_start.month
    )
    for week_days in month_weeks:
        week = []
        for day in week_days:
            in_month = day.month == month_start.month
            in_range = in_month and range_start <= day <= today
            count = daily_counts.get(day, 0) if in_range else 0
            if in_range and count > 0:
                active_days += 1
            if count:
                title = gettext("%(date)s — %(count)s answers") % {
                    "date": day.isoformat(),
                    "count": count,
                }
            else:
                title = gettext("%(date)s — No activity") % {"date": day.isoformat()}
            week.append(
                {
                    "date": day,
                    "count": count,
                    "level": _activity_level(count),
                    "title": title,
                    "in_month": in_month,
                    "in_range": in_range,
                }
            )
        weeks.append(week)

    return {
        "weeks": weeks,
        "active_days": active_days,
        "range_days": ACTIVITY_DAYS,
        "month_label": date_format(month_start, "F Y"),
        "month_value": month_start.strftime("%Y-%m"),
        "has_prev": month_start > earliest_month,
        "has_next": month_start < latest_month,
        "prev_month": _previous_month(month_start).strftime("%Y-%m"),
        "next_month": _next_month(month_start).strftime("%Y-%m"),
    }
