from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_customer_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="activated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="customer_activation_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

