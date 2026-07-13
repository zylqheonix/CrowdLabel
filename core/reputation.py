from django.db.models import Count, F, OuterRef, Subquery

from .models import WorkerAnswer

STARTING_REPUTATION = 100
REPUTATION_GAIN = {1: 2, 2: 3, 3: 3, 4: 5}
REPUTATION_LOSS = {1: 1, 2: 1, 3: 1, 4: 2}
REPUTATION_FLOOR = 0


def _latest_answer_aggregates(user):
    latest_pk = WorkerAnswer.objects.filter(
        user=user,
        task_id=OuterRef("task_id"),
    ).order_by("-created_at").values("pk")[:1]

    return (
        WorkerAnswer.objects.filter(user=user)
        .annotate(latest_pk=Subquery(latest_pk))
        .filter(pk=F("latest_pk"))
        .values("task__complexity", "is_correct")
        .annotate(count=Count("id"))
    )


def _reputation_from_aggregates(aggregates):
    rep = STARTING_REPUTATION
    correct = 0
    wrong = 0

    for row in aggregates:
        complexity = row["task__complexity"]
        is_correct = row["is_correct"]
        count = row["count"]
        if is_correct is None:
            continue
        if is_correct:
            correct += count
            rep += REPUTATION_GAIN.get(complexity, 0) * count
        else:
            wrong += count
            rep -= REPUTATION_LOSS.get(complexity, 0) * count

    if REPUTATION_FLOOR is not None:
        rep = max(rep, REPUTATION_FLOOR)
    return rep, correct, wrong


def calculate_reputation(user):
    """Quality score from latest verified answers, weighted by task difficulty."""
    aggregates = list(_latest_answer_aggregates(user))
    score, _, _ = _reputation_from_aggregates(aggregates)
    return score


def reputation_summary(user):
    aggregates = list(_latest_answer_aggregates(user))
    score, correct, wrong = _reputation_from_aggregates(aggregates)
    return {
        "score": score,
        "correct": correct,
        "wrong": wrong,
    }
