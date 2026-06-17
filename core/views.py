from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from .auth_data import ROLE_REDIRECTS
from .models import User, WorkerScore
from .tasks_data import QUESTIONS


def landing(request):
    return render(request, "core/landing.html")


def _redirect_for_role(role):
    """Resolve the post-login destination from the user's role."""
    destination = ROLE_REDIRECTS.get(role, "tasks")
    return redirect(destination)


def register(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username:
            return render(request, "core/register.html", {"error": "Username is required"})
        if User.objects.filter(username=username).exists():
            return render(request, "core/register.html", {"error": "Username already taken"})
        if len(password) < 6:
            return render(
                request,
                "core/register.html",
                {"error": "Password must be at least 6 characters"},
            )

        # create_user hashes the password via Django's auth system.
        # Registration only ever creates workers; admins are seeded separately.
        user = User.objects.create_user(
            username=username, password=password, role=User.WORKER
        )
        auth_login(request, user)
        return redirect("tasks")

    return render(request, "core/register.html")


def login(request):
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            auth_login(request, user)
            # Route on the user's role, not on the username.
            return _redirect_for_role(user.role)

        return render(
            request,
            "core/login.html",
            {"error": "Invalid credentials, try again"},
        )

    return render(request, "core/login.html")


def logout(request):
    auth_logout(request)
    return redirect("landing")


@login_required
def tasks(request):
    if request.method == "POST":
        index = _parse_index(request.POST.get("index"))
        question = QUESTIONS[index] if 0 <= index < len(QUESTIONS) else None
        if question is None:
            return render(request, "core/tasks.html", {"finished": True})

        selected = request.POST.get("answer")
        is_correct = selected == question["correct"]
        # The first question (index 0) starts a fresh quiz run, so reset the
        # score; later questions accumulate within that same run.
        _record_result(request.user, is_correct, is_new_quiz=index == 0)

        return render(
            request,
            "core/tasks.html",
            {
                "question": question,
                "index": index,
                "selected": selected,
                "answered": True,
                "is_correct": is_correct,
                "next_index": index + 1,
                "has_next": index + 1 < len(QUESTIONS),
            },
        )

    index = _parse_index(request.GET.get("q"))
    if index >= len(QUESTIONS):
        return render(request, "core/tasks.html", {"finished": True})

    return render(
        request,
        "core/tasks.html",
        {"question": QUESTIONS[index], "index": index},
    )


def _record_result(user, is_correct, is_new_quiz):
    """Store the result for the current quiz run in the worker's single row.

    Starting a new quiz resets the counts so the row reflects only the most
    recent run; subsequent questions in that run accumulate.
    """
    if is_new_quiz:
        base_correct, base_attempted = 0, 0
    else:
        existing = WorkerScore.objects.filter(user=user).first()
        base_correct = existing.correct if existing else 0
        base_attempted = existing.attempted if existing else 0

    WorkerScore.objects.update_or_create(
        user=user,
        defaults={
            "correct": base_correct + (1 if is_correct else 0),
            "attempted": base_attempted + 1,
        },
    )


def _parse_index(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


@login_required
def dashboard(request):
    # Server-side access control: only admins may view the dashboard.
    if request.user.role != User.ADMIN:
        return render(request, "core/not_authorized.html", status=403)

    rows = []
    for worker in User.objects.filter(role=User.WORKER):
        score = getattr(worker, "score", None)
        correct = score.correct if score else 0
        attempted = score.attempted if score else 0
        accuracy = correct / attempted if attempted else 0
        rows.append(
            {
                "username": worker.username,
                "correct": correct,
                "attempted": attempted,
                "accuracy_pct": f"{accuracy * 100:.0f}%" if attempted else "—",
                # Sort keys: accuracy first, then attempted as tiebreaker.
                # Zero-attempt workers fall to the bottom via accuracy = 0.
                "_accuracy": accuracy,
                "_attempted": attempted,
            }
        )

    rows.sort(key=lambda r: (r["_accuracy"], r["_attempted"]), reverse=True)
    return render(request, "core/dashboard.html", {"rows": rows})
