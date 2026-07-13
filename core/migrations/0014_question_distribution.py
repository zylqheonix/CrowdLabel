from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_task_resolution_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformConfig",
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
                (
                    "distribution_mode",
                    models.CharField(
                        choices=[("manual", "Manual"), ("auto", "Auto")],
                        default="manual",
                        max_length=8,
                    ),
                ),
            ],
            options={
                "verbose_name": "platform configuration",
            },
        ),
        migrations.AddField(
            model_name="project",
            name="serving_boost",
            field=models.FloatField(default=1.0),
        ),
        migrations.AddField(
            model_name="project",
            name="serving_weight",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
