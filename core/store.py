from django.db import transaction
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .models import PurchasedBadge
from .points import get_balance, spend_points

STORE_BADGES = {
    "early_bird": {
        "label": _("Early Bird"),
        "cost": 50,
        "emoji": "🌅",
        "desc": _("A shiny placeholder badge."),
    },
    "night_owl": {
        "label": _("Night Owl"),
        "cost": 50,
        "emoji": "🦉",
        "desc": _("Another placeholder badge."),
    },
    "trailblazer": {
        "label": _("Trailblazer"),
        "cost": 150,
        "emoji": "🔥",
        "desc": _("A pricier placeholder badge."),
    },
    "legend": {
        "label": _("Legend"),
        "cost": 300,
        "emoji": "👑",
        "desc": _("The flex placeholder badge."),
    },
}


def format_spend_reason(reason):
    if reason.startswith("store:"):
        key = reason.split(":", 1)[1]
        badge = STORE_BADGES.get(key)
        if badge:
            return gettext("Store: %(label)s") % {"label": badge["label"]}
    return reason


def store_catalog(user):
    owned = set(
        PurchasedBadge.objects.filter(user=user).values_list("badge_key", flat=True)
    )
    balance = get_balance(user)
    items = []
    for key, config in STORE_BADGES.items():
        cost = config["cost"]
        items.append(
            {
                "key": key,
                "label": config["label"],
                "emoji": config["emoji"],
                "desc": config["desc"],
                "cost": cost,
                "owned": key in owned,
                "affordable": balance >= cost,
            }
        )
    return items


def purchased_badges_for_display(user):
    badges = []
    for purchase in PurchasedBadge.objects.filter(user=user).order_by("purchased_at"):
        config = STORE_BADGES.get(purchase.badge_key)
        if not config:
            continue
        badges.append(
            {
                "key": purchase.badge_key,
                "label": config["label"],
                "emoji": config["emoji"],
            }
        )
    return badges


def buy_badge(user, badge_key):
    if badge_key not in STORE_BADGES:
        return False, gettext("Unknown badge.")

    config = STORE_BADGES[badge_key]
    cost = config["cost"]

    with transaction.atomic():
        list(
            PurchasedBadge.objects.select_for_update()
            .filter(user=user)
            .values_list("id", flat=True)
        )
        if PurchasedBadge.objects.filter(user=user, badge_key=badge_key).exists():
            return False, gettext("Already owned.")

        success, message = spend_points(user, cost, reason=f"store:{badge_key}")
        if not success:
            return False, message

        PurchasedBadge.objects.create(user=user, badge_key=badge_key)

    return True, gettext("You bought %(label)s!") % {"label": config["label"]}
