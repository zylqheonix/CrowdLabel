"""Shared factories for CrowdLabel tests."""

from django.http import QueryDict
from django.utils.text import slugify

from core.models import PlatformConfig, Project, Task, User


def make_user(username, role=User.WORKER, password="pass12345", email=None):
    if email is None:
        email = f"{username}@example.com"
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
        role=role,
    )


def make_project(name="Test Project", *, slug=None, **kwargs):
    defaults = {
        "slug": slug or slugify(name) or "project",
        "status": Project.ACTIVE,
        "is_active": True,
    }
    defaults.update(kwargs)
    return Project.objects.create(name=name, **defaults)


def make_task(project, task_id="task-1", **kwargs):
    defaults = {
        "project": project,
        "task_id": task_id,
        "choices": {"a": "Alpha", "b": "Beta"},
        "complexity": 1,
        "is_active": True,
        "correct_answer": "a",
    }
    defaults.update(kwargs)
    return Task.objects.create(**defaults)


def set_distribution_mode(mode):
    config = PlatformConfig.load()
    config.distribution_mode = mode
    config.save(update_fields=["distribution_mode"])
    return config


def query_get(**params):
    """Build a QueryDict like request.GET for review/analytics helpers."""
    query = QueryDict(mutable=True)
    for key, value in params.items():
        if isinstance(value, list):
            query.setlist(key, value)
        else:
            query[key] = value
    return query
