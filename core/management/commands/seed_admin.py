from django.core.management.base import BaseCommand

from core.models import User

# TODO: prototype only — change admin credentials before any real deployment
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


class Command(BaseCommand):
    help = "Create the prototype admin user if it doesn't already exist."

    def handle(self, *args, **options):
        if User.objects.filter(username=ADMIN_USERNAME).exists():
            self.stdout.write(f"Admin user '{ADMIN_USERNAME}' already exists.")
            return

        # create_user hashes the password via Django's auth system.
        User.objects.create_user(
            username=ADMIN_USERNAME,
            password=ADMIN_PASSWORD,
            role=User.ADMIN,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created admin user '{ADMIN_USERNAME}'.")
        )
