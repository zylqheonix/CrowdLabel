import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_earnedbadge"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerStreak",
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
                ("current_streak", models.IntegerField(default=0)),
                ("longest_streak", models.IntegerField(default=0)),
                ("last_completed_date", models.DateField(blank=True, null=True)),
                ("has_freeze", models.BooleanField(default=False)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="streak",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
