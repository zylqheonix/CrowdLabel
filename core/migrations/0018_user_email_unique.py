from django.db import migrations, models


def normalize_user_emails(apps, schema_editor):
    User = apps.get_model("core", "User")
    seen = set()
    for user in User.objects.order_by("id"):
        email = (user.email or "").strip().lower()
        if not email:
            email = f"{user.username}@crowdlabel.local"
        base = email
        suffix = 2
        while email in seen:
            local, _, domain = base.partition("@")
            email = f"{local}+{suffix}@{domain}" if domain else f"{base}+{suffix}"
            suffix += 1
        seen.add(email)
        if user.email != email:
            user.email = email
            user.save(update_fields=["email"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_email_otp"),
    ]

    operations = [
        migrations.RunPython(normalize_user_emails, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(
                max_length=254,
                unique=True,
                verbose_name="email address",
            ),
        ),
    ]
