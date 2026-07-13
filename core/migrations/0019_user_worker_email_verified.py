from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_user_email_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="worker_email_verified",
            field=models.BooleanField(default=True),
        ),
    ]

