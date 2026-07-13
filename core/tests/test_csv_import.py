"""CSV import parsers — admin vs customer row semantics."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.csv_import import (
    CsvUploadError,
    iter_csv_rows,
    parse_admin_task_row,
    parse_customer_task_row,
    read_uploaded_csv,
)
from core.models import Task

from .helpers import make_project, make_task


class AdminCsvParserTests(TestCase):
    def test_parses_standard_row(self):
        row = {
            "task_id": "admin-1",
            "lang": "en",
            "category": "cat",
            "type": "mcq",
            "topic": "sports",
            "complexity": "2",
            "image": "http://example.com/img.png",
            "task": "Pick one",
            "choices": '{"a": "One", "b": "Two"}',
            "correct_answer": "a",
            "is_goldtask": "true",
        }
        task_id, defaults = parse_admin_task_row(row)
        self.assertEqual(task_id, "admin-1")
        self.assertTrue(defaults["is_goldtask"])
        self.assertTrue(defaults["is_active"])
        self.assertEqual(defaults["region_tag"], "sports")
        self.assertEqual(defaults["complexity"], 2)

    def test_missing_task_id_raises(self):
        with self.assertRaises(ValueError):
            parse_admin_task_row({"choices": '{"a": "x"}'})


class CustomerCsvParserTests(TestCase):
    def test_customer_rows_start_inactive(self):
        row = {
            "lang": "en",
            "category": "cat",
            "type": "mcq",
            "topic": "news",
            "complexity": "1",
            "image": "",
            "task": "Question",
            "choices": '{"a": "Yes", "b": "No"}',
            "correct_answer": "a",
        }
        task_id, defaults = parse_customer_task_row(row)
        self.assertTrue(task_id)
        self.assertFalse(defaults["is_active"])
        self.assertTrue(defaults["is_goldtask"])

    def test_customer_row_without_answer_is_not_gold(self):
        row = {
            "task_id": "cust-plain",
            "choices": '{"a": "Yes", "b": "No"}',
            "correct_answer": "",
            "task": "Question",
        }
        _, defaults = parse_customer_task_row(row)
        self.assertFalse(defaults["is_goldtask"])

    def test_generates_unique_task_id_when_missing(self):
        project = make_project("CSV", slug="csv-proj")
        make_task(project, task_id="existing")
        row = {"choices": '{"a": "x", "b": "y"}', "task": "Q"}
        task_id, _ = parse_customer_task_row(row)
        self.assertNotEqual(task_id, "existing")
        self.assertFalse(Task.objects.filter(task_id=task_id).exists())

    def test_rejects_non_json_choices(self):
        with self.assertRaises(ValueError):
            parse_customer_task_row(
                {"task": "Q", "choices": "{'a': 'x'}"}
            )

    def test_rejects_oversized_choices_json(self):
        huge = '{"a": "' + ("x" * 9000) + '"}'
        with self.assertRaises(ValueError):
            parse_customer_task_row({"task": "Q", "choices": huge})


@override_settings(CSV_UPLOAD_MAX_BYTES=128, CSV_UPLOAD_MAX_ROWS=3)
class CsvUploadLimitTests(TestCase):
    def test_read_upload_rejects_large_file(self):
        upload = SimpleUploadedFile(
            "tasks.csv",
            b"x" * 200,
            content_type="text/csv",
        )
        with self.assertRaises(CsvUploadError):
            read_uploaded_csv(upload)

    def test_iter_csv_rows_enforces_row_cap(self):
        text = "task_id,choices,task\n" + "\n".join(
            f't{i},"{{""a"":""x""}}",Q' for i in range(5)
        )
        with self.assertRaises(CsvUploadError):
            list(iter_csv_rows(text))

    def test_read_upload_decodes_utf8_csv(self):
        upload = SimpleUploadedFile(
            "tasks.csv",
            "task_id,choices,task\n1,\"{\"\"a\"\":\"\"x\"\"}\",Q\n".encode(),
            content_type="text/csv",
        )
        text = read_uploaded_csv(upload)
        self.assertIn("task_id", text)
