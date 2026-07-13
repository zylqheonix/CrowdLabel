from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Built-in Django user extended with a role used for redirects/access."""

    WORKER = "worker"
    ADMIN = "admin"
    CUSTOMER = "customer"
    ROLE_CHOICES = [
        (WORKER, _("Worker")),
        (ADMIN, _("Admin")),
        (CUSTOMER, _("Customer")),
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=WORKER)
    email = models.EmailField(_("email address"), unique=True)
    worker_email_verified = models.BooleanField(default=True)
    customer_email_verified = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)


class Project(models.Model):
    """A customer labeling project — tasks belong to one project."""

    PENDING = "pending"
    ACTIVE = "active"
    STATUS_CHOICES = [
        (PENDING, _("Pending")),
        (ACTIVE, _("Active")),
    ]

    DEADLINE_REQUEST_NONE = "none"
    DEADLINE_REQUEST_PENDING = "pending"
    DEADLINE_REQUEST_HANDLED = "handled"
    DEADLINE_REQUEST_CHOICES = [
        (DEADLINE_REQUEST_NONE, _("None")),
        (DEADLINE_REQUEST_PENDING, _("Pending")),
        (DEADLINE_REQUEST_HANDLED, _("Handled")),
    ]

    name = models.CharField(max_length=128)
    customer = models.CharField(max_length=128, blank=True)
    slug = models.SlugField(max_length=140, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_projects",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=ACTIVE)
    is_active = models.BooleanField(default=True)
    deadline = models.DateField(null=True, blank=True)
    alert_lead_days = models.PositiveIntegerField(default=7)
    is_complete = models.BooleanField(default=False)
    serving_weight = models.PositiveIntegerField(default=0)
    serving_boost = models.FloatField(default=1.0)
    requested_deadline = models.DateField(null=True, blank=True)
    deadline_request_note = models.TextField(blank=True)
    deadline_request_status = models.CharField(
        max_length=16,
        choices=DEADLINE_REQUEST_CHOICES,
        default=DEADLINE_REQUEST_NONE,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    customer_activation_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._unique_slug(slugify(self.name) or "project")
        super().save(*args, **kwargs)

    def _unique_slug(self, base):
        slug = base
        suffix = 2
        while Project.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def __str__(self):
        return self.name

    @property
    def days_until_deadline(self):
        """Signed day delta from local 'today' to deadline (None if no deadline)."""
        if self.deadline is None:
            return None
        today = timezone.localdate()
        return (self.deadline - today).days

    @property
    def deadline_status(self):
        """Deadline state used for alerts and UI.

        Returns one of: complete, no_deadline, overdue, due_today, approaching, on_track
        """
        if self.is_complete:
            return "complete"
        if self.deadline is None:
            return "no_deadline"

        today = timezone.localdate()
        if self.deadline < today:
            return "overdue"
        if self.deadline == today:
            return "due_today"

        # Approaching: within (today, today + alert_lead_days]
        approaching_until = today + timedelta(days=int(self.alert_lead_days or 0))
        if today < self.deadline <= approaching_until:
            return "approaching"

        return "on_track"

    @property
    def deadline_status_label(self):
        mapping = {
            "complete": "Complete",
            "no_deadline": "No deadline",
            "overdue": "Overdue",
            "due_today": "Due today",
            "approaching": "Approaching",
            "on_track": "On track",
        }
        code = self.deadline_status
        return mapping.get(code, code.replace("_", " ").title())


class PlatformConfig(models.Model):
    """Singleton row for global admin knobs (question distribution mode, etc.)."""

    MANUAL = "manual"
    AUTO = "auto"
    MODE_CHOICES = [
        (MANUAL, _("Manual")),
        (AUTO, _("Auto")),
    ]

    distribution_mode = models.CharField(
        max_length=8,
        choices=MODE_CHOICES,
        default=MANUAL,
    )

    class Meta:
        verbose_name = _("platform configuration")

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Task(models.Model):
    """A single labeling task, loaded via CSV upload."""

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="tasks",
    )
    task_id = models.CharField(max_length=64, unique=True)
    language = models.CharField(max_length=16, blank=True)
    category = models.CharField(max_length=32, blank=True)
    format = models.CharField(max_length=16, blank=True)
    region_tag = models.CharField(max_length=32, blank=True)
    complexity = models.IntegerField(null=True, blank=True)
    num_choices = models.IntegerField(default=0)
    image = models.URLField(max_length=500, blank=True)
    task = models.TextField(blank=True)
    # e.g. {"a": "green", "b": "gray", "c": "red", "d": "cyan"}
    choices = models.JSONField(default=dict)
    # null/blank for non-honeypot tasks with no known answer
    correct_answer = models.CharField(max_length=8, null=True, blank=True)
    is_goldtask = models.BooleanField(default=False)
    admin_resolved_answer = models.CharField(max_length=8, null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_tasks",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    @property
    def ground_truth(self):
        """Canonical answer key for review surfaces."""
        # Gold and regular tasks currently share the same stored answer field.
        return self.correct_answer

    def __str__(self):
        return self.task_id


class WorkerScore(models.Model):
    """One row per worker, holding their most recent quiz run's results."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="score",
    )
    correct = models.IntegerField(default=0)
    attempted = models.IntegerField(default=0)
    preferred_topics = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.user.username}: {self.correct}/{self.attempted}"


class WorkerAnswer(models.Model):
    """One submission per worker per task."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="answers")
    selected_answer = models.CharField(max_length=8)
    # Null means the task had no known correct answer, so it was not scorable.
    is_correct = models.BooleanField(null=True)
    verified = models.BooleanField(default=False)
    time_taken_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "task"],
                name="core_workeranswer_user_task_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} -> {self.task.task_id}: {self.selected_answer}"


class EarnedBadge(models.Model):
    """Badge tier permanently earned by a worker."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="earned_badges",
    )
    badge_key = models.CharField(max_length=32)
    tier = models.CharField(max_length=16)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "badge_key", "tier")

    def __str__(self):
        return f"{self.user.username}: {self.badge_key} {self.tier}"


class WorkerStreak(models.Model):
    """Daily task-completion streak for a worker."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="streak",
    )
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    last_completed_date = models.DateField(null=True, blank=True)
    has_freeze = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username}: {self.current_streak}-day streak"


class PointsSpend(models.Model):
    """Append-only ledger of points spent by a worker."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="point_spends",
    )
    amount = models.PositiveIntegerField()
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: -{self.amount} ({self.reason})"


class Invite(models.Model):
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="invites",
    )
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    invitee = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="referred_by_invite",
    )

    def __str__(self):
        return f"{self.inviter.username}: {self.token}"


class PurchasedBadge(models.Model):
    """Cosmetic badge bought from the points store."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="purchased_badges",
    )
    badge_key = models.CharField(max_length=32)
    purchased_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "badge_key")

    def __str__(self):
        return f"{self.user.username}: {self.badge_key} (purchased)"


class EmailOTP(models.Model):
    """One-time codes for admin login 2FA, signup email verify, and worker recovery."""

    PURPOSE_LOGIN = "login_2fa"
    PURPOSE_WORKER_SIGNUP = "worker_signup"
    PURPOSE_CUSTOMER_SIGNUP = "customer_signup"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, _("Login verification")),
        (PURPOSE_WORKER_SIGNUP, _("Worker signup verification")),
        (PURPOSE_CUSTOMER_SIGNUP, _("Customer signup verification")),
        (PURPOSE_PASSWORD_RESET, _("Password reset")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_otps",
    )
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "purpose", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} {self.purpose} @ {self.created_at:%Y-%m-%d %H:%M}"
