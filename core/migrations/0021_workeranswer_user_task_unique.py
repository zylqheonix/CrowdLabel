from django.db import migrations, models
from django.db.models import Count


def dedupe_worker_answers(apps, schema_editor):
    WorkerAnswer = apps.get_model("core", "WorkerAnswer")
    duplicates = (
        WorkerAnswer.objects.values("user_id", "task_id")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    for row in duplicates.iterator():
        keep = (
            WorkerAnswer.objects.filter(user_id=row["user_id"], task_id=row["task_id"])
            .order_by("-created_at", "-id")
            .first()
        )
        if keep is None:
            continue
        (
            WorkerAnswer.objects.filter(user_id=row["user_id"], task_id=row["task_id"])
            .exclude(pk=keep.pk)
            .delete()
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_customer_email_verified"),
    ]

    operations = [
        migrations.RunPython(dedupe_worker_answers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="workeranswer",
            constraint=models.UniqueConstraint(
                fields=("user", "task"),
                name="core_workeranswer_user_task_uniq",
            ),
        ),
    ]
