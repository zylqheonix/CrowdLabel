from django.contrib import admin

from .models import Invite, PointsSpend, Project, PurchasedBadge, WorkerScore


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "customer", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "customer", "slug")
    readonly_fields = ("created_at", "slug")


@admin.register(WorkerScore)
class WorkerScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "correct", "attempted", "preferred_topics")
    list_filter = ("user",)
    search_fields = ("user__username",)
    readonly_fields = ("user",)


@admin.register(PointsSpend)
class PointsSpendAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "reason", "created_at")
    list_filter = ("user",)
    search_fields = ("user__username", "reason")
    readonly_fields = ("created_at",)


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("inviter", "token", "invitee", "accepted_at", "created_at")
    list_filter = ("inviter", "accepted_at")
    search_fields = ("inviter__username", "invitee__username", "token")
    readonly_fields = ("created_at", "token")


@admin.register(PurchasedBadge)
class PurchasedBadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "badge_key", "purchased_at")
    list_filter = ("badge_key",)
    search_fields = ("user__username", "badge_key")
    readonly_fields = ("purchased_at",)
