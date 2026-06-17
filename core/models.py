from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Built-in Django user extended with a role used for redirects/access."""

    WORKER = "worker"
    ADMIN = "admin"
    ROLE_CHOICES = [
        (WORKER, "Worker"),
        (ADMIN, "Admin"),
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=WORKER)


class WorkerScore(models.Model):
    """One row per worker, holding their most recent quiz run's results."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="score",
    )
    correct = models.IntegerField(default=0)
    attempted = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username}: {self.correct}/{self.attempted}"
