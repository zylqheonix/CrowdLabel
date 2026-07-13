from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_user_worker_email_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="customer_email_verified",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="emailotp",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("login_2fa", "Login verification"),
                    ("worker_signup", "Worker signup verification"),
                    ("customer_signup", "Customer signup verification"),
                    ("password_reset", "Password reset"),
                ],
                max_length=20,
            ),
        ),
    ]
