from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_project_activation_notice_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailOTP",
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
                    "purpose",
                    models.CharField(
                        choices=[
                            ("login_2fa", "Login verification"),
                            ("password_reset", "Password reset"),
                        ],
                        max_length=20,
                    ),
                ),
                ("code_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_otps",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="emailotp",
            index=models.Index(
                fields=["user", "purpose", "-created_at"],
                name="core_emailo_user_id_6f0a8a_idx",
            ),
        ),
    ]
