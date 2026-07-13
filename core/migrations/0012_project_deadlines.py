from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_project"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="deadline",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="alert_lead_days",
            field=models.PositiveIntegerField(default=7),
        ),
        migrations.AddField(
            model_name="project",
            name="is_complete",
            field=models.BooleanField(default=False),
        ),
    ]

