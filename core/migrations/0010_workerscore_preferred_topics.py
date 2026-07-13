from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_purchasedbadge"),
    ]

    operations = [
        migrations.AddField(
            model_name="workerscore",
            name="preferred_topics",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
