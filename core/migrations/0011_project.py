from django.db import migrations, models
import django.db.models.deletion


def create_default_project_and_backfill(apps, schema_editor):
    Project = apps.get_model("core", "Project")
    Task = apps.get_model("core", "Task")
    default, _ = Project.objects.get_or_create(
        slug="default",
        defaults={
            "name": "Default",
            "customer": "",
            "is_active": True,
        },
    )
    Task.objects.filter(project__isnull=True).update(project=default)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_workerscore_preferred_topics"),
    ]

    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=128)),
                ("customer", models.CharField(blank=True, max_length=128)),
                ("slug", models.SlugField(max_length=140, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddField(
            model_name="task",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tasks",
                to="core.project",
            ),
        ),
        migrations.RunPython(
            create_default_project_and_backfill,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="task",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tasks",
                to="core.project",
            ),
        ),
    ]
