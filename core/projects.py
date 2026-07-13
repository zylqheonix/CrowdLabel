"""Project scoping helpers — single source of truth for admin querysets."""

from django.db.models import Count, Q

from .models import Project, Task, WorkerAnswer


def _to_int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def resolve_project_scope(request_get):
    """Return (project_id, selected_value, all_projects).

    project_id is None when viewing all projects.
    selected_value is 'all', a project id string, or '' when no projects exist.
    Defaults to the first active project when no ?project= param is present.
    """
    all_projects = list(Project.objects.order_by("name"))
    param = request_get.get("project", "").strip()

    if param == "all":
        return None, "all", all_projects

    if param:
        pid = _to_int(param)
        if pid and any(project.id == pid for project in all_projects):
            return pid, str(pid), all_projects

    active = [project for project in all_projects if project.is_active and project.status == Project.ACTIVE]
    if active:
        return active[0].id, str(active[0].id), all_projects
    if all_projects:
        return all_projects[0].id, str(all_projects[0].id), all_projects
    return None, "", all_projects


def scoped_tasks_queryset(project_id=None, *, active_only=False):
    """Base Task queryset for admin surfaces and the worker pool."""
    qs = Task.objects.all()
    if active_only:
        qs = qs.filter(
            is_active=True,
            project__is_active=True,
            project__status=Project.ACTIVE,
        )
    if project_id is not None:
        qs = qs.filter(project_id=project_id)
    return qs.order_by("id")


def scoped_answers_queryset(project_id=None):
    qs = WorkerAnswer.objects.all()
    if project_id is not None:
        qs = qs.filter(task__project_id=project_id)
    return qs


def projects_with_counts():
    return (
        Project.objects.order_by("name")
        .annotate(
            task_count=Count("tasks"),
            gold_count=Count("tasks", filter=Q(tasks__is_goldtask=True)),
        )
    )


def pending_customer_setup_projects():
    """Customer-uploaded projects awaiting admin activation."""
    return (
        Project.objects.filter(status=Project.PENDING, owner__isnull=False)
        .annotate(task_count=Count("tasks"))
        .select_related("owner")
        .order_by("created_at")
    )


def project_scope_context(request_get):
    project_id, selected_project, all_projects = resolve_project_scope(request_get)
    return {
        "projects": all_projects,
        "project_scope_id": project_id,
        "selected_project": selected_project,
    }
