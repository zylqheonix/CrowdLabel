from .models import Project


def build_admin_deadline_alerts():
    """Live-computed deadline alerts for admin dashboard."""
    alert_statuses = {"approaching", "due_today", "overdue"}
    projects_qs = Project.objects.filter(is_complete=False, deadline__isnull=False)

    alerts = []
    for project in projects_qs:
        status = project.deadline_status
        if status not in alert_statuses:
            continue

        days = project.days_until_deadline
        day_phrase = ""
        if status == "overdue":
            abs_days = abs(days or 0)
            day_phrase = f"overdue by {abs_days} day" + ("s" if abs_days != 1 else "")
        elif status == "due_today":
            day_phrase = "due today"
        elif status == "approaching":
            day_phrase = f"due in {days} day" + ("s" if (days or 0) != 1 else "")

        severity_class = (
            "deadline-sev-overdue"
            if status == "overdue"
            else ("deadline-sev-due-today" if status == "due_today" else "deadline-sev-approaching")
        )

        alerts.append(
            {
                "project": project,
                "status": status,
                "status_label": project.deadline_status_label,
                "days_until_deadline": days,
                "day_phrase": day_phrase,
                "severity_class": severity_class,
            }
        )

    alerts.sort(key=lambda a: a["days_until_deadline"])
    return alerts

