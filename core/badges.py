from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .models import EarnedBadge, WorkerAnswer, WorkerStreak
from .points import calculate_points


BADGES = {
    "points": {
        "label": _("Points"),
        "bronze": 100,
        "silver": 300,
        "gold": 750,
        "points_reward": {"bronze": 0, "silver": 0, "gold": 0},
    },
    "tasks_completed": {
        "label": _("Tasks Completed"),
        "bronze": 10,
        "silver": 25,
        "gold": 50,
        "points_reward": {"bronze": 25, "silver": 50, "gold": 100},
    },
    "streak": {
        "label": _("Daily Streak"),
        "bronze": 10,
        "silver": 50,
        "gold": 100,
        "points_reward": {"bronze": 25, "silver": 50, "gold": 100},
    },
}

TIER_ORDER = ["bronze", "silver", "gold"]

TIER_LABELS = {
    "bronze": _("Bronze"),
    "silver": _("Silver"),
    "gold": _("Gold"),
}


def badge_metrics(user):
    streak, _created = WorkerStreak.objects.get_or_create(user=user)
    return {
        "points": calculate_points(user),
        "tasks_completed": WorkerAnswer.objects.filter(user=user)
        .values("task_id")
        .distinct()
        .count(),
        "streak": streak.longest_streak,
    }


def _award_badge_tiers(user, badge_key, current_value, newly_created):
    config = BADGES[badge_key]
    for tier in TIER_ORDER:
        if current_value >= config[tier]:
            badge, created = EarnedBadge.objects.get_or_create(
                user=user,
                badge_key=badge_key,
                tier=tier,
            )
            if created:
                newly_created.append(badge)


def reconcile_badges(user):
    metrics = badge_metrics(user)
    newly_created = []

    for badge_key in BADGES:
        if badge_key == "points":
            continue
        _award_badge_tiers(user, badge_key, metrics[badge_key], newly_created)

    earned = calculate_points(user)
    _award_badge_tiers(user, "points", earned, newly_created)

    return newly_created


def trophy_room_data(user):
    metrics = badge_metrics(user)
    earned = {
        (badge.badge_key, badge.tier)
        for badge in EarnedBadge.objects.filter(user=user)
    }
    cards = []

    for badge_key, config in BADGES.items():
        current_value = metrics.get(badge_key, 0)
        earned_tiers = [tier for tier in TIER_ORDER if (badge_key, tier) in earned]
        next_tier = None
        next_threshold = None
        for tier in TIER_ORDER:
            if tier not in earned_tiers:
                next_tier = tier
                next_threshold = config[tier]
                break

        if next_threshold:
            progress_percent = min(100, int((current_value / next_threshold) * 100))
            progress_text = gettext("%(label)s: %(tier)s - %(current)s / %(threshold)s") % {
                "label": config["label"],
                "tier": TIER_LABELS[next_tier],
                "current": current_value,
                "threshold": next_threshold,
            }
        else:
            progress_percent = 100
            progress_text = gettext("Maxed out")

        cards.append(
            {
                "key": badge_key,
                "label": config["label"],
                "current_value": current_value,
                "tiers": [
                    {
                        "name": tier,
                        "label": TIER_LABELS[tier],
                        "threshold": config[tier],
                        "earned": tier in earned_tiers,
                    }
                    for tier in TIER_ORDER
                ],
                "next_tier": next_tier,
                "next_threshold": next_threshold,
                "progress_percent": progress_percent,
                "progress_text": progress_text,
            }
        )

    return cards


def badge_toast_items(badges):
    items = []
    for badge in badges:
        config = BADGES.get(badge.badge_key, {})
        items.append(
            {
                "label": config.get("label", badge.badge_key),
                "tier": TIER_LABELS.get(badge.tier, badge.tier),
            }
        )
    return items
