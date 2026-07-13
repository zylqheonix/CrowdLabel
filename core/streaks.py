from django.utils import timezone
from django.utils.translation import gettext

from .models import WorkerStreak

STREAK_FREEZE_THRESHOLD = 5


def _streak_toast_payload(previous, current, earned_freeze=False):
    return {
        "increased": True,
        "previous": previous,
        "current": current,
        "earned_freeze": earned_freeze,
    }


def advance_streak(user):
    """Advance the worker's streak after completing a task (idempotent per day)."""
    today = timezone.localdate()
    streak, _ = WorkerStreak.objects.get_or_create(user=user)
    previous = streak.current_streak
    earned_freeze = False
    had_freeze = streak.has_freeze

    if streak.last_completed_date is None:
        streak.current_streak = 1
    else:
        gap_days = (today - streak.last_completed_date).days
        if gap_days == 0:
            return {
                "increased": False,
                "previous": previous,
                "current": previous,
                "earned_freeze": False,
            }
        if gap_days == 1:
            streak.current_streak += 1
        elif gap_days == 2 and streak.has_freeze:
            streak.has_freeze = False
            streak.current_streak += 1
        else:
            streak.current_streak = 1
            streak.has_freeze = False

    streak.last_completed_date = today
    streak.longest_streak = max(streak.longest_streak, streak.current_streak)
    if streak.current_streak >= STREAK_FREEZE_THRESHOLD and not had_freeze:
        streak.has_freeze = True
        earned_freeze = True
    streak.save()
    return _streak_toast_payload(previous, streak.current_streak, earned_freeze)


def refresh_streak_display(user):
    """Read streak state on dashboard load; detect breaks without incrementing."""
    today = timezone.localdate()
    streak, _ = WorkerStreak.objects.get_or_create(user=user)

    if streak.last_completed_date is None:
        return {
            "current_streak": 0,
            "longest_streak": streak.longest_streak,
            "has_freeze": streak.has_freeze,
            "status_message": "",
        }

    gap_days = (today - streak.last_completed_date).days

    if gap_days == 0:
        status_message = gettext("completed today")
    elif gap_days == 1:
        status_message = gettext("do a task today to keep your streak")
    elif gap_days == 2 and streak.has_freeze:
        status_message = gettext("protection will save your streak today")
    else:
        streak.current_streak = 0
        streak.has_freeze = False
        streak.save()
        status_message = gettext("streak lost")

    return {
        "current_streak": streak.current_streak,
        "longest_streak": streak.longest_streak,
        "has_freeze": streak.has_freeze,
        "status_message": status_message,
    }
