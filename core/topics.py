from .models import WorkerScore
from .projects import scoped_tasks_queryset


def distinct_region_tags():
    return list(
        scoped_tasks_queryset(active_only=True)
        .exclude(region_tag="")
        .values_list("region_tag", flat=True)
        .distinct()
        .order_by("region_tag")
    )


def get_preferred_topics(user):
    score = WorkerScore.objects.filter(user=user).first()
    if not score or not score.preferred_topics:
        return []
    return list(score.preferred_topics)


def topic_filter_active(user):
    return bool(get_preferred_topics(user))


def save_preferred_topics(user, submitted_topics):
    valid = set(distinct_region_tags())
    cleaned = [tag for tag in submitted_topics if tag in valid]
    score, _ = WorkerScore.objects.get_or_create(user=user)
    score.preferred_topics = cleaned
    score.save(update_fields=["preferred_topics"])
    return cleaned


def apply_topic_filter(queryset, user):
    topics = get_preferred_topics(user)
    if topics:
        return queryset.filter(region_tag__in=topics)
    return queryset
