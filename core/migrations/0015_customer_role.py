from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_active_status(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    Task = apps.get_model("core", "Task")
    Project.objects.all().update(status="active")
    Task.objects.all().update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_question_distribution"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("worker", "Worker"),
                    ("admin", "Admin"),
                    ("customer", "Customer"),
                ],
                default="worker",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="deadline_request_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="project",
            name="deadline_request_status",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("pending", "Pending"),
                    ("handled", "Handled"),
                ],
                default="none",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="owned_projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="requested_deadline",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="status",
            field=models.CharField(
                choices=[("pending", "Pending"), ("active", "Active")],
                default="active",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(backfill_active_status, migrations.RunPython.noop),
    ]
