"""CSV task import helpers — shared between admin and customer upload flows."""

import csv
import io
import json
import secrets

from django.conf import settings
from django.utils.translation import gettext

from .models import Task

CUSTOMER_CSV_COLUMNS = [
    "task_id",
    "lang",
    "category",
    "type",
    "topic",
    "complexity",
    "image",
    "task",
    "choices",
    "correct_answer",
]

CUSTOMER_IGNORED_COLUMNS = {
    "status",
    "llm_answer",
    "confidence_level",
    "submitted_answer",
    "llm_info",
    "user_answers",
    "track_id",
    "id",
    "hint",
}


class CsvUploadError(Exception):
    """Raised when an uploaded CSV fails size or shape validation."""


def csv_upload_max_bytes():
    return getattr(settings, "CSV_UPLOAD_MAX_BYTES", 2_621_440)


def csv_upload_max_rows():
    return getattr(settings, "CSV_UPLOAD_MAX_ROWS", 10_000)


def csv_choices_max_bytes():
    return getattr(settings, "CSV_CHOICES_MAX_BYTES", 8_192)


def read_uploaded_csv(upload):
    """Read and decode an uploaded CSV file with a hard byte cap."""
    if upload is None:
        raise CsvUploadError(gettext("Please choose a CSV file."))

    max_bytes = csv_upload_max_bytes()
    if getattr(upload, "size", None) and upload.size > max_bytes:
        raise CsvUploadError(
            gettext("CSV file is too large (max %(max_mb)s MB).")
            % {"max_mb": round(max_bytes / (1024 * 1024), 1)}
        )

    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise CsvUploadError(
            gettext("CSV file is too large (max %(max_mb)s MB).")
            % {"max_mb": round(max_bytes / (1024 * 1024), 1)}
        )

    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvUploadError(gettext("File must be a UTF-8 encoded CSV.")) from exc


def iter_csv_rows(text):
    """Yield (line_no, row) tuples; abort when row cap is exceeded."""
    reader = csv.DictReader(io.StringIO(text))
    max_rows = csv_upload_max_rows()
    row_count = 0
    for line_no, row in enumerate(reader, start=2):
        row_count += 1
        if row_count > max_rows:
            raise CsvUploadError(
                gettext("CSV has too many rows (max %(max_rows)s).")
                % {"max_rows": max_rows}
            )
        yield line_no, row


def _row_value(row, *keys):
    for key in keys:
        if key in row and (row.get(key) or "").strip():
            return (row.get(key) or "").strip()
    return ""


def _parse_choices(raw):
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("missing choices")
    if len(raw.encode("utf-8")) > csv_choices_max_bytes():
        raise ValueError("choices JSON is too large")
    try:
        choices = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("choices must be valid JSON") from exc
    if not isinstance(choices, dict):
        raise ValueError("choices must be a JSON object")
    return choices


def _parse_optional_int(raw):
    try:
        raw = (raw or "").strip()
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def generate_task_id():
    for _ in range(10):
        task_id = secrets.token_urlsafe(9)
        if not Task.objects.filter(task_id=task_id).exists():
            return task_id
    return secrets.token_urlsafe(16)


def parse_admin_task_row(row):
    """Turn one admin CSV row dict into Task field values."""
    task_id = _row_value(row, "task_id")
    if not task_id:
        raise ValueError("missing task_id")

    choices = _parse_choices(row.get("choices"))
    correct = _row_value(row, "correct_answer") or None
    num_choices = int(row.get("num_choices") or 0) or len(choices)

    defaults = {
        "language": _row_value(row, "language", "lang"),
        "category": _row_value(row, "category"),
        "format": _row_value(row, "format", "type"),
        "region_tag": _row_value(row, "region_tag", "topic"),
        "complexity": _parse_optional_int(row.get("complexity")),
        "num_choices": num_choices,
        "image": _row_value(row, "image"),
        "task": _row_value(row, "task"),
        "choices": choices,
        "correct_answer": correct,
        "is_active": True,
    }
    flag_value = _get_goldtask_value(row)
    if flag_value is not None:
        defaults["is_goldtask"] = flag_value
    return task_id, defaults


def parse_customer_task_row(row):
    """Parse a customer-upload CSV row; auto-generates task_id when absent."""
    task_id = _row_value(row, "task_id") or generate_task_id()
    choices = _parse_choices(row.get("choices"))
    correct = _row_value(row, "correct_answer") or None
    num_choices = len(choices)

    defaults = {
        "language": _row_value(row, "lang", "language"),
        "category": _row_value(row, "category"),
        "format": _row_value(row, "type", "format"),
        "region_tag": _row_value(row, "topic", "region_tag"),
        "complexity": _parse_optional_int(row.get("complexity")),
        "num_choices": num_choices,
        "image": _row_value(row, "image"),
        "task": _row_value(row, "task"),
        "choices": choices,
        "correct_answer": correct,
        "is_goldtask": bool(correct),
        "is_active": False,
    }
    return task_id, defaults


def _get_goldtask_value(row):
    for column in ("is_goldtask", "goldtask", "is_gold", "gold", "validation_task"):
        if column in row and (row.get(column) or "").strip():
            return (row.get(column) or "").strip().lower() == "true"
    return None
