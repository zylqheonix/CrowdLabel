from django.db import transaction
from django.db.models import Case, Count, IntegerField, Sum, Value, When
from django.utils.translation import gettext

from .models import EarnedBadge, Invite, PointsSpend, Task, User, WorkerAnswer

COMPLETION_POINTS = 5
DIFFICULTY_POINTS = {1: 5, 2: 10, 3: 10, 4: 15}
REFERRAL_REWARD_POINTS = 30
REFERRAL_REWARD_CAP = 10
POINTS_LEADERBOARD_SIZE = 5


def _completion_points(user):
    distinct_tasks = (
        WorkerAnswer.objects.filter(user=user)
        .aggregate(count=Count("task_id", distinct=True))["count"]
        or 0
    )
    return COMPLETION_POINTS * distinct_tasks


def _correctness_bonus_points(user):
    bonus_cases = [
        When(complexity=level, then=Value(points))
        for level, points in DIFFICULTY_POINTS.items()
    ]
    return (
        Task.objects.filter(answers__user=user, answers__is_correct=True)
        .distinct()
        .aggregate(
            total=Sum(
                Case(
                    *bonus_cases,
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
        )["total"]
        or 0
    )


def _badge_reward_points(user):
    from .badges import BADGES

    earned_badges = EarnedBadge.objects.filter(user=user).values_list(
        "badge_key", "tier"
    )
    total = 0
    for badge_key, tier in earned_badges:
        rewards = BADGES.get(badge_key, {}).get("points_reward", {})
        total += rewards.get(tier, 0)
    return total


def _successful_referral_count(user):
    return Invite.objects.filter(
        inviter=user,
        accepted_at__isnull=False,
        invitee__isnull=False,
    ).count()


def _referral_points(user):
    successful = _successful_referral_count(user)
    return min(successful, REFERRAL_REWARD_CAP) * REFERRAL_REWARD_POINTS


def calculate_points(user):
    """Lifetime earned points — single source of truth for badges and display."""
    return (
        _completion_points(user)
        + _correctness_bonus_points(user)
        + _badge_reward_points(user)
        + _referral_points(user)
    )


def get_spent(user):
    return (
        PointsSpend.objects.filter(user=user).aggregate(total=Sum("amount"))["total"] or 0
    )


def get_balance(user):
    return calculate_points(user) - get_spent(user)


def points_summary(user):
    earned = calculate_points(user)
    spent = get_spent(user)
    successful = _successful_referral_count(user)
    return {
        "earned": earned,
        "spent": spent,
        "balance": earned - spent,
        "referrals_successful": successful,
        "referrals_cap": REFERRAL_REWARD_CAP,
        "referral_reward_points": REFERRAL_REWARD_POINTS,
    }


def spend_points(user, amount, reason):
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return False, gettext("Amount must be a positive integer.")

    with transaction.atomic():
        list(
            PointsSpend.objects.select_for_update()
            .filter(user=user)
            .values_list("id", flat=True)
        )
        balance = get_balance(user)
        if balance < amount:
            return False, gettext("Not enough points")
        PointsSpend.objects.create(user=user, amount=amount, reason=reason)
        return True, gettext("Spent %(amount)s points.") % {"amount": amount}


def get_points_leaderboard(current_user):
    """Top workers by lifetime earned points plus the current worker's rank.

    Ranked by calculate_points (lifetime earned), not spendable balance — a worker
    must not drop the board for spending in the store.
    """
    rows = []
    for worker in User.objects.filter(role=User.WORKER).order_by("id"):
        rows.append(
            {
                "user_id": worker.id,
                "username": worker.username,
                "points": calculate_points(worker),
            }
        )

    rows.sort(key=lambda row: (-row["points"], row["user_id"]))

    ranked = [{**row, "rank": index} for index, row in enumerate(rows, start=1)]

    current_row = next(row for row in ranked if row["user_id"] == current_user.id)

    top = [
        {
            "rank": row["rank"],
            "username": row["username"],
            "points": row["points"],
            "is_current_user": row["user_id"] == current_user.id,
        }
        for row in ranked[:POINTS_LEADERBOARD_SIZE]
    ]

    return {
        "top": top,
        "current_user": {
            "rank": current_row["rank"],
            "username": current_row["username"],
            "points": current_row["points"],
        },
        "in_top": current_row["rank"] <= POINTS_LEADERBOARD_SIZE,
    }
