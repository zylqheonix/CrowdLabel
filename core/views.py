from datetime import datetime
import json
import secrets
import smtplib
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.paginator import Paginator
from django.db.models import Avg, Count
from django.db import IntegrityError
from django.http import HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import check_for_language, gettext
from django.utils.translation import gettext_lazy as _

from .auth_data import REGISTERABLE_ROLES, ROLE_REDIRECTS
from .badges import badge_toast_items, reconcile_badges, trophy_room_data
from .history import activity_calendar, answer_history_sections
from .reputation import reputation_summary
from .analytics import build_admin_analytics
from .review_queue import (
    build_review_queue,
    build_resolve_context,
)
from .points import calculate_points, get_balance, get_points_leaderboard, get_spent, points_summary
from .projects import (
    pending_customer_setup_projects,
    project_scope_context,
    projects_with_counts,
    scoped_tasks_queryset,
)
from .context_processors import build_admin_deadline_alerts
from .csv_import import (
    CUSTOMER_CSV_COLUMNS,
    CsvUploadError,
    iter_csv_rows,
    parse_admin_task_row,
    parse_customer_task_row,
    read_uploaded_csv,
)
from .customer_analytics import build_customer_project_analytics, customer_dashboard_rows
from .distribution import (
    build_distribution_page_context,
    pick_task_by_project_deficit,
)
from .models import EmailOTP, Invite, PlatformConfig, PointsSpend, Project, Task, User, WorkerAnswer, WorkerScore
from .store import (
    buy_badge,
    format_spend_reason,
    purchased_badges_for_display,
    store_catalog,
)
from .streaks import advance_streak, refresh_streak_display
from .topics import (
    apply_topic_filter,
    distinct_region_tags,
    get_preferred_topics,
    save_preferred_topics,
    topic_filter_active,
)
from .ratelimit import (
    clear_otp_verify_failures,
    client_ip,
    guard_otp_send,
    guard_otp_verify,
    rate_limit_hit,
    record_otp_verify_failure,
    rate_limit_response,
    too_many_requests_message,
)
from .security import invalidate_user_sessions, password_error, safe_next_url
from .two_factor import (
    create_and_send_otp,
    email_taken,
    is_valid_email_format,
    normalize_email,
    roles_allowing_password_reset,
    roles_requiring_login_2fa,
    verify_otp,
)

CSV_COLUMNS = [
    "task_id",
    "language",
    "category",
    "format",
    "region_tag",
    "complexity",
    "num_choices",
    "image",
    "task",
    "choices",
    "correct_answer",
]

DIFFICULTY_OPTIONS = {
    "easy": {"label": _("Easy"), "description": _("Complexity 1 tasks")},
    "medium": {"label": _("Medium"), "description": _("Complexity 2–3 tasks")},
    "hard": {"label": _("Hard"), "description": _("Complexity 4 tasks")},
}

SESSION_PENDING_LOGIN_USER = "pending_login_user_id"
SESSION_PASSWORD_RESET_VERIFIED = "password_reset_verified_user_id"
SESSION_PASSWORD_RESET_FLOW = "password_reset_flow_started"
SESSION_PENDING_WORKER_VERIFY_USER = "pending_worker_verify_user_id"
SESSION_PENDING_CUSTOMER_VERIFY_USER = "pending_customer_verify_user_id"
SESSION_PENDING_WORKER_INVITE = "pending_worker_invite_token"
OTP_RESEND_COOLDOWN_SECONDS = 30


def admin_required(view):
    """Allow only authenticated admins; everyone else gets a 403 page."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.ADMIN:
            return render(request, "core/not_authorized.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper


def worker_required(view):
    """Allow only authenticated workers; everyone else gets a 403 page."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.WORKER:
            return render(request, "core/not_authorized.html", status=403)
        if request.session.get("pending_onboarding") and view.__name__ != "worker_setup":
            return redirect("worker_setup")
        return view(request, *args, **kwargs)

    return wrapper


def customer_required(view):
    """Allow only authenticated customers."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.CUSTOMER:
            return render(request, "core/not_authorized.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper


def landing(request):
    return render(request, "core/landing.html")


def _redirect_for_role(role):
    """Resolve the post-login destination from the user's role."""
    destination = ROLE_REDIRECTS.get(role, "tasks")
    return redirect(destination)


def _clear_pending_auth_session(request):
    request.session.pop(SESSION_PENDING_LOGIN_USER, None)
    request.session.pop(SESSION_PASSWORD_RESET_VERIFIED, None)
    request.session.pop(SESSION_PASSWORD_RESET_FLOW, None)
    request.session.pop(SESSION_PENDING_WORKER_VERIFY_USER, None)
    request.session.pop(SESSION_PENDING_CUSTOMER_VERIFY_USER, None)
    request.session.pop(SESSION_PENDING_WORKER_INVITE, None)


def _pending_login_user(request):
    user_id = request.session.get(SESSION_PENDING_LOGIN_USER)
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def _start_login_2fa(request, user):
    if not user.email:
        return render(
            request,
            "core/login.html",
            {
                "error": gettext(
                    "This account has no email on file. Ask an administrator to add one."
                ),
            },
        )
    limited = guard_otp_send(request, user)
    if limited is not None:
        return render(
            request,
            "core/login.html",
            {"error": too_many_requests_message(limited.retry_after)},
        )
    try:
        create_and_send_otp(user, EmailOTP.PURPOSE_LOGIN)
    except (smtplib.SMTPException, OSError):
        return render(
            request,
            "core/login.html",
            {
                "error": gettext(
                    "We could not send the verification email right now. Please try again in a moment."
                ),
            },
        )
    request.session[SESSION_PENDING_LOGIN_USER] = user.id
    return redirect("verify_login_otp")


def _start_worker_signup_verification(request, user):
    if not user.email:
        return render(
            request,
            "core/register.html",
            {"error": gettext("Email is required")},
        )
    limited = guard_otp_send(request, user)
    if limited is not None:
        return render(
            request,
            "core/register.html",
            {
                "selected_role": User.WORKER,
                "email_value": user.email,
                "error": too_many_requests_message(limited.retry_after),
            },
        )
    try:
        create_and_send_otp(user, EmailOTP.PURPOSE_WORKER_SIGNUP)
    except (smtplib.SMTPException, OSError):
        return render(
            request,
            "core/register.html",
            {
                "selected_role": User.WORKER,
                "email_value": user.email,
                "error": gettext(
                    "We could not send the verification email right now. Please try again in a moment."
                ),
            },
        )
    request.session[SESSION_PENDING_WORKER_VERIFY_USER] = user.id
    return redirect("verify_worker_signup_otp")


def _start_customer_signup_verification(request, user):
    if not user.email:
        return render(
            request,
            "core/register.html",
            {
                "selected_role": User.CUSTOMER,
                "error": gettext("Email is required"),
            },
        )
    limited = guard_otp_send(request, user)
    if limited is not None:
        return render(
            request,
            "core/register.html",
            {
                "selected_role": User.CUSTOMER,
                "email_value": user.email,
                "error": too_many_requests_message(limited.retry_after),
            },
        )
    try:
        create_and_send_otp(user, EmailOTP.PURPOSE_CUSTOMER_SIGNUP)
    except (smtplib.SMTPException, OSError):
        return render(
            request,
            "core/register.html",
            {
                "selected_role": User.CUSTOMER,
                "email_value": user.email,
                "error": gettext(
                    "We could not send the verification email right now. Please try again in a moment."
                ),
            },
        )
    request.session[SESSION_PENDING_CUSTOMER_VERIFY_USER] = user.id
    return redirect("verify_customer_signup_otp")


def _resend_otp_with_cooldown(request, user, purpose):
    latest = (
        EmailOTP.objects.filter(user=user, purpose=purpose)
        .order_by("-created_at")
        .first()
    )
    if latest is not None:
        elapsed = (timezone.now() - latest.created_at).total_seconds()
        if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
            wait_for = OTP_RESEND_COOLDOWN_SECONDS - int(elapsed)
            if wait_for < 1:
                wait_for = 1
            return False, wait_for
    limited = guard_otp_send(request, user)
    if limited is not None:
        return False, limited.retry_after
    try:
        create_and_send_otp(user, purpose)
    except (smtplib.SMTPException, OSError):
        return False, -1
    return True, 0


def _set_language_cookie(response, language_code):
    if not check_for_language(language_code):
        return response
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language_code,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


def register(request):
    invite_token = request.GET.get("invite", "").strip()
    selected_role = request.GET.get("role", User.WORKER).strip()
    if selected_role not in REGISTERABLE_ROLES:
        selected_role = User.WORKER

    if request.method == "POST":
        limited = rate_limit_hit("register", client_ip(request))
        if limited.limited:
            return render(
                request,
                "core/register.html",
                {
                    "invite_token": invite_token,
                    "selected_role": selected_role,
                    "error": too_many_requests_message(limited.retry_after),
                },
            )

        invite_token = request.POST.get("invite_token", "").strip()
        username = request.POST.get("username", "").strip()
        email = normalize_email(request.POST.get("email", ""))
        password = request.POST.get("password", "")
        role = request.POST.get("role", User.WORKER).strip()

        if role not in REGISTERABLE_ROLES:
            return HttpResponseBadRequest("Invalid registration role.")

        register_context = {
            "invite_token": invite_token,
            "selected_role": role if role in REGISTERABLE_ROLES else User.WORKER,
            "email_value": email,
        }

        if not username:
            return render(
                request,
                "core/register.html",
                {**register_context, "error": gettext("Username is required")},
            )
        if not email:
            return render(
                request,
                "core/register.html",
                {**register_context, "error": gettext("Email is required")},
            )
        if not is_valid_email_format(email):
            return render(
                request,
                "core/register.html",
                {**register_context, "error": gettext("Enter a valid email address")},
            )
        if email_taken(email):
            return render(
                request,
                "core/register.html",
                {**register_context, "error": gettext("Email already in use")},
            )
        if User.objects.filter(username=username).exists():
            return render(
                request,
                "core/register.html",
                {**register_context, "error": gettext("Username already taken")},
            )
        password_issue = password_error(
            password, user=User(username=username, email=email, role=role)
        )
        if password_issue:
            return render(
                request,
                "core/register.html",
                {**register_context, "error": password_issue},
            )

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role=role,
            )
        except IntegrityError:
            return render(
                request,
                "core/register.html",
                {**register_context, "error": gettext("Email already in use")},
            )
        if role == User.CUSTOMER:
            user.customer_email_verified = False
            user.save(update_fields=["customer_email_verified"])
            return _start_customer_signup_verification(request, user)

        user.worker_email_verified = False
        user.save(update_fields=["worker_email_verified"])
        request.session[SESSION_PENDING_WORKER_INVITE] = invite_token
        return _start_worker_signup_verification(request, user)

    return render(
        request,
        "core/register.html",
        {"invite_token": invite_token, "selected_role": selected_role},
    )


def customer_register(request):
    """Legacy URL — single registration page handles role selection."""
    role = request.GET.get("role", User.CUSTOMER).strip()
    if role not in REGISTERABLE_ROLES:
        role = User.CUSTOMER
    return redirect(f"{reverse('register')}?role={role}")


def login(request):
    if request.method == "POST":
        limited = rate_limit_hit("login_ip", client_ip(request))
        if limited.limited:
            return render(
                request,
                "core/login.html",
                {"error": too_many_requests_message(limited.retry_after)},
            )

        username = request.POST.get("username", "")
        password = request.POST.get("password", "")

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.role == User.WORKER and not user.worker_email_verified:
                return _start_worker_signup_verification(request, user)
            if user.role == User.CUSTOMER and not user.customer_email_verified:
                return _start_customer_signup_verification(request, user)
            if user.role in roles_requiring_login_2fa():
                return _start_login_2fa(request, user)
            auth_login(request, user)
            return _redirect_for_role(user.role)

        fail_limit = rate_limit_hit("login_fail", client_ip(request), username)
        if fail_limit.limited:
            return render(
                request,
                "core/login.html",
                {"error": too_many_requests_message(fail_limit.retry_after)},
            )

        return render(
            request,
            "core/login.html",
            {"error": gettext("Invalid credentials, try again")},
        )

    return render(request, "core/login.html")


def verify_worker_signup_otp(request):
    user_id = request.session.get(SESSION_PENDING_WORKER_VERIFY_USER)
    user = User.objects.filter(pk=user_id, role=User.WORKER).first()
    if user is None:
        return redirect("register")

    if request.method == "POST":
        action = request.POST.get("action", "verify").strip()
        if action == "resend":
            sent, wait_for = _resend_otp_with_cooldown(
                request, user, EmailOTP.PURPOSE_WORKER_SIGNUP
            )
            if sent:
                messages.success(request, gettext("A new verification code was sent to your email."))
            elif wait_for == -1:
                messages.error(
                    request,
                    gettext("We could not send the verification email right now. Please try again in a moment."),
                )
            else:
                messages.error(
                    request,
                    gettext("Please wait %(seconds)s seconds before requesting another code.")
                    % {"seconds": wait_for},
                )
            return redirect("verify_worker_signup_otp")

        code = request.POST.get("code", "").strip()
        locked = guard_otp_verify(request, user)
        if locked is not None:
            return render(
                request,
                "core/verify_worker_signup_otp.html",
                {
                    "email_masked": _mask_email(user.email),
                    "error": too_many_requests_message(locked.retry_after),
                },
            )

        if verify_otp(user, EmailOTP.PURPOSE_WORKER_SIGNUP, code):
            clear_otp_verify_failures(request, user)
            user.worker_email_verified = True
            user.save(update_fields=["worker_email_verified"])
            request.session.pop(SESSION_PENDING_WORKER_VERIFY_USER, None)
            auth_login(request, user)
            invite_token = request.session.pop(SESSION_PENDING_WORKER_INVITE, "")
            _accept_invite(invite_token, user)
            request.session["pending_onboarding"] = True
            return redirect("worker_setup")

        fail_limit = record_otp_verify_failure(request, user)
        error = (
            too_many_requests_message(fail_limit.retry_after)
            if fail_limit.limited
            else gettext("Invalid or expired code. Try again or request a new one.")
        )
        return render(
            request,
            "core/verify_worker_signup_otp.html",
            {
                "email_masked": _mask_email(user.email),
                "error": error,
            },
        )

    return render(
        request,
        "core/verify_worker_signup_otp.html",
        {"email_masked": _mask_email(user.email)},
    )


def verify_customer_signup_otp(request):
    user_id = request.session.get(SESSION_PENDING_CUSTOMER_VERIFY_USER)
    user = User.objects.filter(pk=user_id, role=User.CUSTOMER).first()
    if user is None:
        return redirect("register")

    if request.method == "POST":
        action = request.POST.get("action", "verify").strip()
        if action == "resend":
            sent, wait_for = _resend_otp_with_cooldown(
                request, user, EmailOTP.PURPOSE_CUSTOMER_SIGNUP
            )
            if sent:
                messages.success(request, gettext("A new verification code was sent to your email."))
            elif wait_for == -1:
                messages.error(
                    request,
                    gettext("We could not send the verification email right now. Please try again in a moment."),
                )
            else:
                messages.error(
                    request,
                    gettext("Please wait %(seconds)s seconds before requesting another code.")
                    % {"seconds": wait_for},
                )
            return redirect("verify_customer_signup_otp")

        code = request.POST.get("code", "").strip()
        locked = guard_otp_verify(request, user)
        if locked is not None:
            return render(
                request,
                "core/verify_customer_signup_otp.html",
                {
                    "email_masked": _mask_email(user.email),
                    "error": too_many_requests_message(locked.retry_after),
                },
            )

        if verify_otp(user, EmailOTP.PURPOSE_CUSTOMER_SIGNUP, code):
            clear_otp_verify_failures(request, user)
            user.customer_email_verified = True
            user.save(update_fields=["customer_email_verified"])
            request.session.pop(SESSION_PENDING_CUSTOMER_VERIFY_USER, None)
            auth_login(request, user)
            return redirect("customer_dashboard")

        fail_limit = record_otp_verify_failure(request, user)
        error = (
            too_many_requests_message(fail_limit.retry_after)
            if fail_limit.limited
            else gettext("Invalid or expired code. Try again or request a new one.")
        )
        return render(
            request,
            "core/verify_customer_signup_otp.html",
            {
                "email_masked": _mask_email(user.email),
                "error": error,
            },
        )

    return render(
        request,
        "core/verify_customer_signup_otp.html",
        {"email_masked": _mask_email(user.email)},
    )


def verify_login_otp(request):
    user = _pending_login_user(request)
    if user is None:
        return redirect("login")

    if request.method == "POST":
        action = request.POST.get("action", "verify").strip()
        if action == "resend":
            sent, wait_for = _resend_otp_with_cooldown(request, user, EmailOTP.PURPOSE_LOGIN)
            if sent:
                messages.success(request, gettext("A new verification code was sent to your email."))
            elif wait_for == -1:
                messages.error(
                    request,
                    gettext("We could not send the verification email right now. Please try again in a moment."),
                )
            else:
                messages.error(
                    request,
                    gettext("Please wait %(seconds)s seconds before requesting another code.")
                    % {"seconds": wait_for},
                )
            return redirect("verify_login_otp")

        code = request.POST.get("code", "").strip()
        locked = guard_otp_verify(request, user)
        if locked is not None:
            return render(
                request,
                "core/verify_login_otp.html",
                {
                    "email_masked": _mask_email(user.email),
                    "error": too_many_requests_message(locked.retry_after),
                },
            )

        if verify_otp(user, EmailOTP.PURPOSE_LOGIN, code):
            clear_otp_verify_failures(request, user)
            request.session.pop(SESSION_PENDING_LOGIN_USER, None)
            auth_login(request, user)
            return _redirect_for_role(user.role)

        fail_limit = record_otp_verify_failure(request, user)
        error = (
            too_many_requests_message(fail_limit.retry_after)
            if fail_limit.limited
            else gettext("Invalid or expired code. Try again or request a new one.")
        )
        return render(
            request,
            "core/verify_login_otp.html",
            {
                "email_masked": _mask_email(user.email),
                "error": error,
            },
        )

    return render(
        request,
        "core/verify_login_otp.html",
        {"email_masked": _mask_email(user.email)},
    )


def forgot_password(request):
    if request.method == "POST":
        ip_limit = rate_limit_hit("forgot_password", client_ip(request))
        if ip_limit.limited:
            return render(
                request,
                "core/forgot_password.html",
                {"error": too_many_requests_message(ip_limit.retry_after)},
            )

        email = normalize_email(request.POST.get("email", ""))
        if not email:
            return render(
                request,
                "core/forgot_password.html",
                {"error": gettext("Email is required")},
            )

        email_limit = rate_limit_hit("forgot_password_email", email)
        if email_limit.limited:
            return render(
                request,
                "core/forgot_password.html",
                {"error": too_many_requests_message(email_limit.retry_after)},
            )

        user = (
            User.objects.filter(email__iexact=email, role__in=roles_allowing_password_reset())
            .order_by("id")
            .first()
        )
        request.session[SESSION_PASSWORD_RESET_FLOW] = True
        if user:
            limited = guard_otp_send(request, user)
            if limited is not None:
                messages.error(
                    request,
                    too_many_requests_message(limited.retry_after),
                )
                return redirect("verify_reset_otp")
            try:
                create_and_send_otp(user, EmailOTP.PURPOSE_PASSWORD_RESET)
                request.session[SESSION_PENDING_LOGIN_USER] = user.id
            except (smtplib.SMTPException, OSError):
                messages.error(
                    request,
                    gettext("We could not send the verification email right now. Please try again in a moment."),
                )
                return redirect("verify_reset_otp")
        else:
            request.session.pop(SESSION_PENDING_LOGIN_USER, None)

        messages.success(
            request,
            gettext(
                "If an account exists for that email, we sent a verification code."
            ),
        )
        return redirect("verify_reset_otp")

    return render(request, "core/forgot_password.html")


def _password_reset_verify_context(request, *, error=None):
    user = _pending_login_user(request)
    if user is not None and user.role in roles_allowing_password_reset():
        return {
            "email_masked": _mask_email(user.email),
            "generic_reset_copy": False,
            "error": error,
        }
    if request.session.get(SESSION_PASSWORD_RESET_FLOW):
        return {
            "email_masked": None,
            "generic_reset_copy": True,
            "error": error,
        }
    return None


def verify_reset_otp(request):
    context = _password_reset_verify_context(request)
    if context is None:
        return redirect("forgot_password")

    user = _pending_login_user(request)

    if request.method == "POST":
        action = request.POST.get("action", "verify").strip()
        if action == "resend":
            if user is None or user.role not in roles_allowing_password_reset():
                messages.success(
                    request,
                    gettext(
                        "If an account exists for that email, we sent a verification code."
                    ),
                )
                return redirect("verify_reset_otp")

            sent, wait_for = _resend_otp_with_cooldown(
                request, user, EmailOTP.PURPOSE_PASSWORD_RESET
            )
            if sent:
                messages.success(request, gettext("A new verification code was sent to your email."))
            elif wait_for == -1:
                messages.error(
                    request,
                    gettext("We could not send the verification email right now. Please try again in a moment."),
                )
            else:
                messages.error(
                    request,
                    gettext("Please wait %(seconds)s seconds before requesting another code.")
                    % {"seconds": wait_for},
                )
            return redirect("verify_reset_otp")

        if user is None or user.role not in roles_allowing_password_reset():
            fail_limit = rate_limit_hit("otp_verify_fail", client_ip(request), "reset")
            error = (
                too_many_requests_message(fail_limit.retry_after)
                if fail_limit.limited
                else gettext("Invalid or expired code. Try again or request a new one.")
            )
            return render(request, "core/verify_reset_otp.html", {**context, "error": error})

        code = request.POST.get("code", "").strip()
        locked = guard_otp_verify(request, user)
        if locked is not None:
            return render(
                request,
                "core/verify_reset_otp.html",
                {**context, "error": too_many_requests_message(locked.retry_after)},
            )

        if verify_otp(user, EmailOTP.PURPOSE_PASSWORD_RESET, code):
            clear_otp_verify_failures(request, user)
            request.session.pop(SESSION_PENDING_LOGIN_USER, None)
            request.session.pop(SESSION_PASSWORD_RESET_FLOW, None)
            request.session[SESSION_PASSWORD_RESET_VERIFIED] = user.id
            return redirect("reset_password")

        fail_limit = record_otp_verify_failure(request, user)
        error = (
            too_many_requests_message(fail_limit.retry_after)
            if fail_limit.limited
            else gettext("Invalid or expired code. Try again or request a new one.")
        )
        return render(
            request,
            "core/verify_reset_otp.html",
            {**context, "error": error},
        )

    return render(request, "core/verify_reset_otp.html", context)


def reset_password(request):
    user_id = request.session.get(SESSION_PASSWORD_RESET_VERIFIED)
    user = User.objects.filter(pk=user_id, role__in=roles_allowing_password_reset()).first()
    if user is None:
        return redirect("forgot_password")

    if request.method == "POST":
        limited = rate_limit_hit("reset_password", client_ip(request))
        if limited.limited:
            return render(
                request,
                "core/reset_password.html",
                {"error": too_many_requests_message(limited.retry_after)},
            )

        password = request.POST.get("password", "")
        confirm = request.POST.get("password_confirm", "")
        password_issue = password_error(password, user=user)
        if password_issue:
            return render(
                request,
                "core/reset_password.html",
                {"error": password_issue},
            )
        if password != confirm:
            return render(
                request,
                "core/reset_password.html",
                {"error": gettext("Passwords do not match")},
            )

        user.set_password(password)
        user.save(update_fields=["password"])
        invalidate_user_sessions(user)
        _clear_pending_auth_session(request)
        messages.success(request, gettext("Password updated. You can log in now."))
        return redirect("login")

    return render(request, "core/reset_password.html")


def _mask_email(email):
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def logout(request):
    _clear_pending_auth_session(request)
    auth_logout(request)
    return redirect("landing")


@login_required
def settings_page(request):
    if request.user.role == User.CUSTOMER:
        return redirect("customer_dashboard")
    if request.user.role == User.WORKER:
        return redirect("profile_security")
    return redirect("dashboard")


@worker_required
def update_username(request):
    if request.method != "POST":
        return redirect("profile_security")

    new_username = request.POST.get("new_username", "").strip()
    current_password = request.POST.get("current_password", "")
    username_error = None

    if not request.user.check_password(current_password):
        username_error = gettext("Current password is incorrect.")
    elif not new_username:
        username_error = gettext("Username is required.")
    elif User.objects.exclude(pk=request.user.pk).filter(username=new_username).exists():
        username_error = gettext("Username already taken.")

    if username_error:
        return render(
            request,
            "core/profile_security.html",
            {
                "profile_tab": "security",
                "username_value": new_username or request.user.username,
                "username_error": username_error,
                "password_form": PasswordChangeForm(user=request.user),
            },
        )

    request.user.username = new_username
    request.user.save(update_fields=["username"])
    messages.success(request, gettext("Username updated."))
    return redirect("profile_security")


@worker_required
def update_password(request):
    if request.method != "POST":
        return redirect("profile_security")

    password_form = PasswordChangeForm(request.user, request.POST)
    if password_form.is_valid():
        user = password_form.save()
        update_session_auth_hash(request, user)
        messages.success(request, gettext("Password updated."))
        return redirect("profile_security")

    return render(
        request,
        "core/profile_security.html",
        {
            "profile_tab": "security",
            "username_value": request.user.username,
            "username_error": None,
            "password_form": password_form,
        },
    )


@worker_required
def create_invite(request):
    if request.method != "POST":
        return redirect("worker_dashboard")

    limited = rate_limit_hit("invite_create", request.user.pk)
    if limited.limited:
        messages.error(request, too_many_requests_message(limited.retry_after))
        return redirect("worker_dashboard")

    invite = _create_invite_for_user(request.user)
    return redirect(f"{reverse('trophy_room')}?invite={invite.token}")


@login_required
def worker_setup(request):
    if request.user.role != User.WORKER:
        return render(request, "core/not_authorized.html", status=403)

    if request.method == "POST":
        language = request.POST.get("language", "en")
        save_preferred_topics(request.user, request.POST.getlist("preferred_topics"))
        request.session.pop("pending_onboarding", None)
        response = redirect("worker_dashboard")
        return _set_language_cookie(response, language)

    return render(
        request,
        "core/worker_setup.html",
        {
            "available_topics": distinct_region_tags(),
            "selected_topics": set(get_preferred_topics(request.user)),
            "current_language": getattr(request, "LANGUAGE_CODE", "en"),
        },
    )


@worker_required
def worker_dashboard(request):
    if request.method == "POST":
        difficulty = request.POST.get("difficulty")
        if difficulty in DIFFICULTY_OPTIONS:
            request.session["difficulty"] = difficulty
            return redirect("tasks")
    new_badges = reconcile_badges(request.user)

    return render(
        request,
        "core/worker_dashboard.html",
        {
            "difficulty_cards": _difficulty_progress(request.user),
            "selected_difficulty": request.session.get("difficulty"),
            "new_badges": badge_toast_items(new_badges),
            "streak": refresh_streak_display(request.user),
            "points": points_summary(request.user),
            "points_leaderboard": get_points_leaderboard(request.user),
            "streak_toast": request.session.pop("streak_toast", None),
        },
    )


@worker_required
def profile_activity(request):
    return render(
        request,
        "core/profile_activity.html",
        {
            "profile_tab": "activity",
            "reputation": reputation_summary(request.user),
            "activity": activity_calendar(request.user, request.GET.get("month")),
        },
    )


@worker_required
def profile_preferences(request):
    if request.method == "POST" and request.POST.get("form") == "topic_preferences":
        submitted = request.POST.getlist("preferred_topics")
        save_preferred_topics(request.user, submitted)
        messages.success(request, gettext("Topic preferences saved."))
        return redirect("profile_preferences")

    available_topics = distinct_region_tags()
    selected_topics = set(get_preferred_topics(request.user))
    return render(
        request,
        "core/profile_preferences.html",
        {
            "profile_tab": "preferences",
            "available_topics": available_topics,
            "selected_topics": selected_topics,
        },
    )


@worker_required
def profile_security(request):
    return render(
        request,
        "core/profile_security.html",
        {
            "profile_tab": "security",
            "username_value": request.user.username,
            "username_error": None,
            "password_form": PasswordChangeForm(user=request.user),
        },
    )


@worker_required
def profile_wallet(request):
    spends = PointsSpend.objects.filter(user=request.user).order_by("-created_at")
    spend_rows = [
        {"spend": spend, "reason_label": format_spend_reason(spend.reason)}
        for spend in spends
    ]
    return render(
        request,
        "core/profile_wallet.html",
        {
            "profile_tab": "wallet",
            "wallet": {
                "earned": calculate_points(request.user),
                "spent": get_spent(request.user),
                "balance": get_balance(request.user),
            },
            "spend_rows": spend_rows,
        },
    )
@worker_required
def worker_activity_month(request):
    limited = rate_limit_hit("activity_month", request.user.pk)
    if limited.limited:
        return rate_limit_response(request, limited, as_json=True)
    activity = activity_calendar(request.user, request.GET.get("month"))
    html = render_to_string(
        "core/partials/activity_calendar.html",
        {"activity": activity},
        request=request,
    )
    return JsonResponse(
        {
            "html": html,
            "month": activity["month_value"],
        }
    )


@worker_required
def worker_history(request):
    return render(
        request,
        "core/history.html",
        {"sections": answer_history_sections(request.user)},
    )


def _store_streak_toast(request, streak_result):
    if not streak_result.get("increased"):
        return
    request.session["streak_toast"] = {
        "previous": streak_result["previous"],
        "current": streak_result["current"],
        "earned_freeze": streak_result.get("earned_freeze", False),
    }


def _difficulty_progress(user):
    cards = []
    answered_task_ids = set(
        WorkerAnswer.objects.filter(user=user).values_list("task_id", flat=True)
    )
    for key, option in DIFFICULTY_OPTIONS.items():
        tier_task_ids = list(
            _tasks_for_difficulty(key, user).values_list("id", flat=True)
        )
        total = len(tier_task_ids)
        completed = len(answered_task_ids.intersection(tier_task_ids))
        percent = int((completed / total) * 100) if total else 0
        cards.append(
            {
                "key": key,
                "label": option["label"],
                "description": option["description"],
                "completed": completed,
                "total": total,
                "percent": percent,
                "is_done": total > 0 and completed == total,
            }
        )
    return cards


@worker_required
def tasks(request):
    difficulty = request.session.get("difficulty")
    if difficulty not in DIFFICULTY_OPTIONS:
        return redirect("worker_dashboard")

    task_queryset = _tasks_for_difficulty(difficulty, request.user)
    total = task_queryset.count()
    show_answer_timer = settings.SHOW_ANSWER_TIMER
    difficulty_label = DIFFICULTY_OPTIONS[difficulty]["label"]
    topics_filtered = topic_filter_active(request.user)

    if request.method == "POST":
        limited = rate_limit_hit("task_submit", request.user.pk)
        if limited.limited:
            messages.error(request, too_many_requests_message(limited.retry_after))
            return redirect("tasks")

        task = task_queryset.filter(id=request.POST.get("task_id")).first()
        if task is None:
            return render(
                request,
                "core/tasks.html",
                {
                    "finished": True,
                    "show_answer_timer": show_answer_timer,
                    "difficulty_label": difficulty_label,
                },
            )

        selected = request.POST.get("answer")
        # Only honeypot/answered tasks can be marked right or wrong; tasks with
        # no known answer are recorded but never counted as correct.
        verified = bool(task.correct_answer)
        is_correct = verified and selected == task.correct_answer
        recorded_is_correct = is_correct if verified else None
        time_taken_seconds = _parse_time_taken(request.POST.get("time_taken_seconds"))

        if WorkerAnswer.objects.filter(user=request.user, task=task).exists():
            has_next = _next_unanswered_task(request.user, difficulty) is not None
            return render(
                request,
                "core/tasks.html",
                {
                    "task": task,
                    "selected": selected,
                    "answered": True,
                    "verified": verified,
                    "is_correct": is_correct,
                    "correct_answer": task.correct_answer,
                    "correct_label": task.choices.get(task.correct_answer) if verified else None,
                    "has_next": has_next,
                    "show_answer_timer": show_answer_timer,
                    "difficulty_label": difficulty_label,
                },
            )

        is_first_answer_in_tier = not WorkerAnswer.objects.filter(
            user=request.user, task__in=task_queryset
        ).exists()
        try:
            WorkerAnswer.objects.create(
                user=request.user,
                task=task,
                selected_answer=selected or "",
                is_correct=recorded_is_correct,
                verified=verified,
                time_taken_seconds=time_taken_seconds,
            )
        except IntegrityError:
            has_next = _next_unanswered_task(request.user, difficulty) is not None
            return render(
                request,
                "core/tasks.html",
                {
                    "task": task,
                    "selected": selected,
                    "answered": True,
                    "verified": verified,
                    "is_correct": is_correct,
                    "correct_answer": task.correct_answer,
                    "correct_label": task.choices.get(task.correct_answer) if verified else None,
                    "has_next": has_next,
                    "show_answer_timer": show_answer_timer,
                    "difficulty_label": difficulty_label,
                },
            )
        streak_result = advance_streak(request.user)
        _store_streak_toast(request, streak_result)
        # The first answered task in a tier starts that tier's run; later
        # answers in the same tier accumulate within the existing aggregate.
        _record_result(request.user, is_correct, is_new_quiz=is_first_answer_in_tier)
        has_next = _next_unanswered_task(request.user, difficulty) is not None

        return render(
            request,
            "core/tasks.html",
            {
                "task": task,
                "selected": selected,
                "answered": True,
                "verified": verified,
                "is_correct": is_correct,
                "correct_answer": task.correct_answer,
                "correct_label": task.choices.get(task.correct_answer) if verified else None,
                "has_next": has_next,
                "show_answer_timer": show_answer_timer,
                "difficulty_label": difficulty_label,
            },
        )

    if total == 0:
        return render(
            request,
            "core/tasks.html",
            {
                "no_tasks": True,
                "show_answer_timer": show_answer_timer,
                "difficulty_label": difficulty_label,
                "topics_filtered": topics_filtered,
            },
        )

    task = _next_unanswered_task(request.user, difficulty)
    if task is None:
        return render(
            request,
            "core/tasks.html",
            {
                "finished": True,
                "show_answer_timer": show_answer_timer,
                "difficulty_label": difficulty_label,
            },
        )

    return render(
        request,
        "core/tasks.html",
        {
            "task": task,
            "show_answer_timer": show_answer_timer,
            "difficulty_label": difficulty_label,
        },
    )


@worker_required
def store_page(request):
    return render(
        request,
        "core/store.html",
        {
            "balance": get_balance(request.user),
            "catalog": store_catalog(request.user),
        },
    )


@worker_required
def buy_badge_view(request):
    if request.method != "POST":
        return redirect("store")

    limited = rate_limit_hit("store_buy", request.user.pk)
    if limited.limited:
        messages.error(request, too_many_requests_message(limited.retry_after))
        return redirect("store")

    badge_key = request.POST.get("badge_key", "").strip()
    success, message = buy_badge(request.user, badge_key)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect("store")


@worker_required
def trophy_room(request):
    new_badges = reconcile_badges(request.user)
    invite_token = request.GET.get("invite", "").strip()
    invite_url = None
    if invite_token:
        invite = Invite.objects.filter(token=invite_token, inviter=request.user).first()
        if invite:
            invite_url = request.build_absolute_uri(reverse("register")) + f"?invite={invite.token}"
    return render(
        request,
        "core/trophy_room.html",
        {
            "badge_cards": trophy_room_data(request.user),
            "new_badges": badge_toast_items(new_badges),
            "points": points_summary(request.user),
            "invite_url": invite_url,
            "share_message": gettext("Join me on CrowdLabel and start earning points."),
            "purchased_badges": purchased_badges_for_display(request.user),
        },
    )


def _tasks_for_difficulty(difficulty, user=None):
    queryset = scoped_tasks_queryset(active_only=True)
    if difficulty == "easy":
        queryset = queryset.filter(complexity=1)
    elif difficulty == "medium":
        queryset = queryset.filter(complexity__in=[2, 3])
    elif difficulty == "hard":
        queryset = queryset.filter(complexity=4)
    else:
        return queryset.none()
    if user is not None:
        queryset = apply_topic_filter(queryset, user)
    return queryset


def _next_unanswered_task(user, difficulty):
    answered_ids = WorkerAnswer.objects.filter(user=user).values_list(
        "task_id", flat=True
    )
    eligible = _tasks_for_difficulty(difficulty, user).exclude(id__in=answered_ids)
    weighted = pick_task_by_project_deficit(user, eligible)
    if weighted is not None:
        return weighted
    return eligible.first()


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


def _parse_time_taken(raw):
    """Return a non-negative elapsed time in seconds, or None if invalid."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _format_seconds(value):
    if value is None:
        return "—"
    return f"{value:.1f}s"


def _review_queue_context(request):
    review_rows, review_summary, review_selected, review_filter_options = build_review_queue(
        request.GET
    )
    review_paginator = Paginator(review_rows, 50)
    review_page_obj = review_paginator.get_page(request.GET.get("review_page"))

    review_query = request.GET.copy()
    review_query.pop("review_page", None)
    review_base_querystring = review_query.urlencode()
    return {
        "review_page_obj": review_page_obj,
        "review_summary": review_summary,
        "review_selected": review_selected,
        "review_filter_options": review_filter_options,
        "review_base_querystring": review_base_querystring,
        **project_scope_context(request.GET),
    }


@admin_required
def dashboard(request):
    total_tasks = Task.objects.count()
    active_projects = Project.objects.filter(is_active=True).count()
    project_rows = list(projects_with_counts())
    completed_by_project = dict(
        WorkerAnswer.objects.values("task__project_id")
        .annotate(completed=Count("task_id", distinct=True))
        .values_list("task__project_id", "completed")
    )
    for project in project_rows:
        completed = completed_by_project.get(project.id, 0)
        total = project.task_count or 0
        project.completed_count = completed
        project.progress_pct = int(round((completed / total) * 100)) if total else 0

    project_rows.sort(key=lambda p: p.name.lower())

    pending_setup_projects = list(pending_customer_setup_projects())

    # Keep answer-time computation code available for future relocation.
    overall_avg_time = WorkerAnswer.objects.exclude(
        time_taken_seconds__isnull=True
    ).aggregate(avg=Avg("time_taken_seconds"))["avg"]

    answer_time_rows = []
    for worker in User.objects.filter(role=User.WORKER).order_by("username"):
        answer_qs = (
            WorkerAnswer.objects.filter(user=worker)
            .select_related("task")
            .order_by("-created_at")
        )
        avg_time = answer_qs.exclude(time_taken_seconds__isnull=True).aggregate(
            avg=Avg("time_taken_seconds")
        )["avg"]
        answer_time_rows.append(
            {
                "username": worker.username,
                "avg_time": _format_seconds(avg_time),
                "answer_count": answer_qs.count(),
                "answers": [
                    {
                        "task_id": answer.task.task_id,
                        "selected_answer": answer.selected_answer,
                        "time_taken": _format_seconds(answer.time_taken_seconds),
                    }
                    for answer in answer_qs
                ],
            }
        )

    return render(
        request,
        "core/dashboard.html",
        {
            "total_tasks": total_tasks,
            "active_projects": active_projects,
            "project_rows": project_rows,
            "overall_avg_answer_time": _format_seconds(overall_avg_time),
            "answer_time_rows": answer_time_rows,
            "admin_deadline_alerts": build_admin_deadline_alerts(),
            "pending_setup_projects": pending_setup_projects,
            "pending_setup_count": len(pending_setup_projects),
            **_review_queue_context(request),
        },
    )


@admin_required
def analytics(request):
    limited = rate_limit_hit("analytics", request.user.pk)
    if limited.limited:
        return rate_limit_response(request, limited)
    context = build_admin_analytics(request.GET)
    return render(request, "core/analytics.html", context)


@admin_required
def review_queue(request):
    return render(
        request,
        "core/review_queue.html",
        _review_queue_context(request),
    )


@admin_required
def resolve_review_item(request, pk):
    task = Task.objects.filter(pk=pk).first()
    if task is None:
        return render(request, "core/not_authorized.html", status=404)

    resolve_data = build_resolve_context(task)
    reveal_truth = task.is_goldtask or request.GET.get("reveal_truth") == "1"
    selected_admin_answer = task.admin_resolved_answer or ""
    local_feedback = None

    if request.method == "POST" and not task.is_goldtask:
        limited = rate_limit_hit("review_resolve", request.user.pk)
        if limited.limited:
            messages.error(request, too_many_requests_message(limited.retry_after))
            return redirect("resolve_review_item", pk=pk)

        action = request.POST.get("action", "save").strip()
        if action == "clear":
            task.admin_resolved_answer = None
            task.resolved_by = None
            task.resolved_at = None
            task.save(update_fields=["admin_resolved_answer", "resolved_by", "resolved_at"])
            selected_admin_answer = ""
            local_feedback = gettext("Resolution cleared.")
        else:
            selected_admin_answer = (request.POST.get("admin_answer") or "").strip()
            if selected_admin_answer and selected_admin_answer in resolve_data["choice_map"]:
                task.admin_resolved_answer = selected_admin_answer
                task.resolved_by = request.user
                task.resolved_at = timezone.now()
                task.save(
                    update_fields=["admin_resolved_answer", "resolved_by", "resolved_at"]
                )
                local_feedback = gettext("Resolution saved.")
            else:
                local_feedback = gettext("Choose a valid answer first.")
        # Refresh to show latest persisted resolution metadata.
        task.refresh_from_db(fields=["admin_resolved_answer", "resolved_by", "resolved_at"])

    return render(
        request,
        "core/review_queue_resolve.html",
        {
            "task_obj": task,
            "resolve_data": resolve_data,
            "reveal_truth": reveal_truth,
            "selected_admin_answer": selected_admin_answer,
            "local_feedback": local_feedback,
            "current_resolution": {
                "answer": task.admin_resolved_answer,
                "label": (
                    resolve_data["choice_map"].get(task.admin_resolved_answer, task.admin_resolved_answer)
                    if task.admin_resolved_answer
                    else None
                ),
                "resolved_by": getattr(task.resolved_by, "username", None),
                "resolved_at": task.resolved_at,
            },
            "back_url": safe_next_url(
                request, request.GET.get("next"), reverse("review_queue")
            ),
        },
    )


@admin_required
def admin_task_detail(request, pk):
    task = Task.objects.filter(pk=pk).first()
    if task is None:
        return render(request, "core/not_authorized.html", status=404)
    return render(
        request,
        "core/task_detail.html",
        {
            "task_obj": task,
            "back_url": safe_next_url(
                request, request.GET.get("next"), reverse("review_queue")
            ),
        },
    )


def _parse_task_row(row):
    return parse_admin_task_row(row)


def _parse_optional_int(raw):
    try:
        raw = (raw or "").strip()
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _activate_project(project):
    project.status = Project.ACTIVE
    project.is_active = True
    project.activated_at = timezone.now()
    project.customer_activation_seen_at = None
    project.save(
        update_fields=["status", "is_active", "activated_at", "customer_activation_seen_at"]
    )
    project.tasks.update(is_active=True)


def _clear_deadline_request(project):
    project.requested_deadline = None
    project.deadline_request_note = ""
    project.deadline_request_status = Project.DEADLINE_REQUEST_HANDLED
    project.save(
        update_fields=[
            "requested_deadline",
            "deadline_request_note",
            "deadline_request_status",
        ]
    )


def _pending_project_preview(project):
    """Build a lightweight upload quality preview before activation."""
    tasks = project.tasks.all()
    sample_tasks = list(
        tasks.order_by("id").values(
            "task_id",
            "category",
            "region_tag",
            "complexity",
            "correct_answer",
            "is_goldtask",
            "task",
            "choices",
        )[:5]
    )
    total = tasks.count()
    gold_count = tasks.filter(is_goldtask=True).count()
    missing_prompt_count = tasks.filter(task__exact="").count()
    missing_choices_count = tasks.filter(choices={}).count()
    low_choice_count = sum(1 for row in sample_tasks if len((row.get("choices") or {})) < 2)
    unresolved_gold_count = tasks.filter(is_goldtask=True, correct_answer__isnull=True).count()

    warnings = []
    if missing_prompt_count:
        warnings.append(
            gettext("%(count)s task rows have no question text.") % {"count": missing_prompt_count}
        )
    if missing_choices_count:
        warnings.append(
            gettext("%(count)s task rows have empty choices.") % {"count": missing_choices_count}
        )
    if low_choice_count:
        warnings.append(
            gettext("%(count)s sampled rows have fewer than 2 choices.")
            % {"count": low_choice_count}
        )
    if unresolved_gold_count:
        warnings.append(
            gettext("%(count)s gold tasks are missing a correct answer.")
            % {"count": unresolved_gold_count}
        )

    return {
        "total_tasks": total,
        "gold_count": gold_count,
        "sample_tasks": sample_tasks,
        "warnings": warnings,
    }


@admin_required
def upload_tasks(request):
    projects = Project.objects.order_by("name")
    if request.method == "POST":
        limited = rate_limit_hit("csv_upload", request.user.pk)
        if limited.limited:
            return render(
                request,
                "core/upload_tasks.html",
                {
                    "error": too_many_requests_message(limited.retry_after),
                    "projects": projects,
                    "columns": CSV_COLUMNS,
                },
            )

        upload = request.FILES.get("csv_file")
        project_id = request.POST.get("project", "").strip()
        project = Project.objects.filter(pk=project_id).first()
        if not project:
            return render(
                request,
                "core/upload_tasks.html",
                {
                    "error": gettext("Please choose a project."),
                    "projects": projects,
                    "columns": CSV_COLUMNS,
                },
            )
        if not upload:
            return render(
                request,
                "core/upload_tasks.html",
                {
                    "error": gettext("Please choose a CSV file."),
                    "projects": projects,
                    "columns": CSV_COLUMNS,
                    "selected_project": project_id,
                },
            )

        try:
            text = read_uploaded_csv(upload)
        except CsvUploadError as exc:
            return render(
                request,
                "core/upload_tasks.html",
                {
                    "error": str(exc),
                    "projects": projects,
                    "columns": CSV_COLUMNS,
                    "selected_project": project_id,
                },
            )

        created = updated = 0
        errors = []
        try:
            row_iter = iter_csv_rows(text)
        except CsvUploadError as exc:
            return render(
                request,
                "core/upload_tasks.html",
                {
                    "error": str(exc),
                    "projects": projects,
                    "columns": CSV_COLUMNS,
                    "selected_project": project_id,
                },
            )

        for line_no, row in row_iter:
            try:
                task_id, defaults = _parse_task_row(row)
            except json.JSONDecodeError:
                errors.append({"row": line_no, "reason": gettext("invalid JSON in choices")})
                continue
            except (ValueError, TypeError) as exc:
                errors.append({"row": line_no, "reason": str(exc)})
                continue

            defaults["project"] = project
            _, was_created = Task.objects.update_or_create(
                task_id=task_id, defaults=defaults
            )
            if was_created:
                created += 1
            else:
                updated += 1

        return render(
            request,
            "core/upload_tasks.html",
            {
                "result": {"created": created, "updated": updated, "errors": errors},
                "projects": projects,
                "columns": CSV_COLUMNS,
                "selected_project": project_id,
            },
        )

    return render(
        request,
        "core/upload_tasks.html",
        {"columns": CSV_COLUMNS, "projects": projects},
    )


@admin_required
def projects_list(request):
    rows = list(projects_with_counts())
    sort = request.GET.get("sort_deadline", "deadline_asc")

    def sort_key(project):
        if project.deadline is None:
            return (1, 0)
        # Nulls last; then sort by date (ascending or descending via values).
        ord_ = project.deadline.toordinal()
        if sort == "deadline_desc":
            return (0, -ord_)
        return (0, ord_)

    rows.sort(key=sort_key)
    rows.sort(key=lambda p: (0 if p.status == Project.PENDING else 1, p.name.lower()))
    pending_deadline_count = Project.objects.filter(
        deadline_request_status=Project.DEADLINE_REQUEST_PENDING
    ).count()
    return render(
        request,
        "core/projects.html",
        {
            "project_rows": rows,
            "pending_deadline_count": pending_deadline_count,
        },
    )


@admin_required
def project_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        customer = request.POST.get("customer", "").strip()
        deadline_raw = (request.POST.get("deadline") or "").strip()
        if deadline_raw:
            deadline = datetime.strptime(deadline_raw, "%Y-%m-%d").date()
        else:
            deadline = None

        alert_lead_days_raw = (request.POST.get("alert_lead_days") or "").strip()
        try:
            alert_lead_days = int(alert_lead_days_raw) if alert_lead_days_raw else 7
            if alert_lead_days < 0:
                alert_lead_days = 0
        except (TypeError, ValueError):
            alert_lead_days = 7

        is_complete = request.POST.get("is_complete") == "on"

        if not name:
            messages.error(request, gettext("Project name is required."))
        else:
            project = Project(
                name=name,
                customer=customer,
                deadline=deadline,
                alert_lead_days=alert_lead_days,
                is_complete=is_complete,
                status=Project.ACTIVE,
            )
            project.save()
            messages.success(request, gettext("Project created."))
            return redirect("projects")
    return render(request, "core/project_form.html", {"form_mode": "create"})


@admin_required
def project_edit(request, pk):
    project = Project.objects.filter(pk=pk).first()
    if project is None:
        return render(request, "core/not_authorized.html", status=404)

    if request.method == "POST":
        action = request.POST.get("action", "save").strip()

        if action == "activate":
            _activate_project(project)
            messages.success(request, gettext("Project activated — tasks are now in the worker pool."))
            return redirect("project_edit", pk=project.pk)

        if action == "approve_deadline":
            if project.requested_deadline:
                project.deadline = project.requested_deadline
                project.save(update_fields=["deadline"])
            _clear_deadline_request(project)
            messages.success(request, gettext("Deadline request approved."))
            return redirect("project_edit", pk=project.pk)

        if action == "dismiss_deadline":
            _clear_deadline_request(project)
            messages.success(request, gettext("Deadline request dismissed."))
            return redirect("project_edit", pk=project.pk)

        name = request.POST.get("name", "").strip()
        customer = request.POST.get("customer", "").strip()
        deadline_raw = (request.POST.get("deadline") or "").strip()
        if deadline_raw:
            deadline = datetime.strptime(deadline_raw, "%Y-%m-%d").date()
        else:
            deadline = None

        alert_lead_days_raw = (request.POST.get("alert_lead_days") or "").strip()
        try:
            alert_lead_days = int(alert_lead_days_raw) if alert_lead_days_raw else 7
            if alert_lead_days < 0:
                alert_lead_days = 0
        except (TypeError, ValueError):
            alert_lead_days = 7

        is_complete = request.POST.get("is_complete") == "on"

        is_active = request.POST.get("is_active") == "on"
        if not name:
            messages.error(request, gettext("Project name is required."))
        else:
            project.name = name
            project.customer = customer
            project.is_active = is_active
            project.deadline = deadline
            project.alert_lead_days = alert_lead_days
            project.is_complete = is_complete
            if is_active and project.status == Project.PENDING:
                project.status = Project.ACTIVE
                project.tasks.update(is_active=True)
            project.save()
            messages.success(request, gettext("Project updated."))
            return redirect("projects")

    task_count = project.tasks.count()
    pending_preview = _pending_project_preview(project) if project.status == Project.PENDING else None
    return render(
        request,
        "core/project_form.html",
        {
            "form_mode": "edit",
            "project": project,
            "is_pending": project.status == Project.PENDING,
            "has_deadline_request": (
                project.deadline_request_status == Project.DEADLINE_REQUEST_PENDING
            ),
            "task_count": task_count,
            "owner_username": getattr(project.owner, "username", None),
            "pending_preview": pending_preview,
        },
    )


@customer_required
def customer_dashboard(request):
    newly_activated = list(
        Project.objects.filter(
            owner=request.user,
            status=Project.ACTIVE,
            activated_at__isnull=False,
            customer_activation_seen_at__isnull=True,
        ).order_by("-activated_at")
    )
    if newly_activated:
        now = timezone.now()
        Project.objects.filter(id__in=[project.id for project in newly_activated]).update(
            customer_activation_seen_at=now
        )
    return render(
        request,
        "core/customer_dashboard.html",
        {
            "project_rows": customer_dashboard_rows(request.user),
            "newly_activated_projects": newly_activated,
        },
    )


@customer_required
def customer_upload(request):
    if request.method == "POST":
        limited = rate_limit_hit("csv_upload", request.user.pk)
        if limited.limited:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": too_many_requests_message(limited.retry_after),
                    "columns": CUSTOMER_CSV_COLUMNS,
                },
            )

        name = request.POST.get("name", "").strip()
        deadline_raw = (request.POST.get("deadline") or "").strip()
        upload = request.FILES.get("csv_file")

        if not name:
            return render(
                request,
                "core/customer_upload.html",
                {"error": gettext("Project name is required."), "columns": CUSTOMER_CSV_COLUMNS},
            )
        if not deadline_raw:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": gettext("Proposed deadline is required."),
                    "columns": CUSTOMER_CSV_COLUMNS,
                    "name": name,
                },
            )
        if not upload:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": gettext("Please choose a CSV file."),
                    "columns": CUSTOMER_CSV_COLUMNS,
                    "name": name,
                    "deadline": deadline_raw,
                },
            )

        try:
            deadline = datetime.strptime(deadline_raw, "%Y-%m-%d").date()
        except ValueError:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": gettext("Invalid deadline date."),
                    "columns": CUSTOMER_CSV_COLUMNS,
                    "name": name,
                    "deadline": deadline_raw,
                },
            )

        try:
            text = read_uploaded_csv(upload)
        except CsvUploadError as exc:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": str(exc),
                    "columns": CUSTOMER_CSV_COLUMNS,
                    "name": name,
                    "deadline": deadline_raw,
                },
            )

        parsed_rows = []
        errors = []
        try:
            row_iter = iter_csv_rows(text)
        except CsvUploadError as exc:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": str(exc),
                    "columns": CUSTOMER_CSV_COLUMNS,
                    "name": name,
                    "deadline": deadline_raw,
                },
            )

        for line_no, row in row_iter:
            try:
                parsed_rows.append(parse_customer_task_row(row))
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append({"row": line_no, "reason": str(exc)})

        if not parsed_rows:
            return render(
                request,
                "core/customer_upload.html",
                {
                    "error": gettext("No valid task rows were imported."),
                    "columns": CUSTOMER_CSV_COLUMNS,
                    "import_errors": errors,
                    "name": name,
                    "deadline": deadline_raw,
                },
            )

        project = Project.objects.create(
            name=name,
            owner=request.user,
            customer=request.user.username,
            deadline=deadline,
            status=Project.PENDING,
            is_active=False,
        )

        created = 0
        for task_id, defaults in parsed_rows:
            defaults["project"] = project
            Task.objects.update_or_create(task_id=task_id, defaults=defaults)
            created += 1

        messages.success(
            request,
            gettext("Project submitted for admin review (%(count)s tasks).") % {"count": created},
        )
        request.session["customer_upload_report"] = {
            "project_id": project.pk,
            "imported": created,
            "skipped": len(errors),
            "errors": errors[:25],
        }
        if errors:
            messages.warning(
                request,
                gettext("%(count)s rows were skipped due to errors.") % {"count": len(errors)},
            )
        return redirect("customer_project_detail", pk=project.pk)

    return render(
        request,
        "core/customer_upload.html",
        {"columns": CUSTOMER_CSV_COLUMNS},
    )


@customer_required
def customer_project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk, owner=request.user)

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "deadline_request":
            deadline_raw = (request.POST.get("requested_deadline") or "").strip()
            note = (request.POST.get("deadline_request_note") or "").strip()
            if not deadline_raw:
                messages.error(request, gettext("Please choose a requested deadline."))
            else:
                try:
                    requested = datetime.strptime(deadline_raw, "%Y-%m-%d").date()
                except ValueError:
                    messages.error(request, gettext("Invalid deadline date."))
                else:
                    project.requested_deadline = requested
                    project.deadline_request_note = note
                    project.deadline_request_status = Project.DEADLINE_REQUEST_PENDING
                    project.save(
                        update_fields=[
                            "requested_deadline",
                            "deadline_request_note",
                            "deadline_request_status",
                        ]
                    )
                    messages.success(request, gettext("Deadline change request submitted."))
            return redirect("customer_project_detail", pk=project.pk)

    context = build_customer_project_analytics(project)
    upload_report = request.session.get("customer_upload_report")
    if upload_report and upload_report.get("project_id") == project.pk:
        context["upload_report"] = upload_report
        request.session.pop("customer_upload_report", None)
    context["has_pending_deadline_request"] = (
        project.deadline_request_status == Project.DEADLINE_REQUEST_PENDING
    )
    return render(request, "core/customer_project_detail.html", context)


def _create_invite_for_user(user):
    for _ in range(5):
        token = secrets.token_urlsafe(16)
        if not Invite.objects.filter(token=token).exists():
            return Invite.objects.create(inviter=user, token=token)
    return Invite.objects.create(inviter=user, token=secrets.token_urlsafe(24))


@admin_required
def project_delete(request, pk):
    project = Project.objects.filter(pk=pk).first()
    if project is None:
        return render(request, "core/not_authorized.html", status=404)

    if request.method == "POST":
        if project.tasks.exists():
            messages.error(
                request,
                gettext(
                    "Cannot delete %(name)s — it still has tasks. Deactivate it instead."
                )
                % {"name": project.name},
            )
        else:
            project.delete()
            messages.success(request, gettext("Project deleted."))
        return redirect("projects")

    return render(
        request,
        "core/project_delete.html",
        {"project": project, "has_tasks": project.tasks.exists()},
    )


@admin_required
def question_distribution(request):
    config = PlatformConfig.load()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()

        if action == "mode":
            mode = request.POST.get("distribution_mode", PlatformConfig.MANUAL).strip()
            if mode in (PlatformConfig.MANUAL, PlatformConfig.AUTO):
                config.distribution_mode = mode
                config.save(update_fields=["distribution_mode"])
                messages.success(request, gettext("Distribution mode updated."))

        elif action == "manual":
            for project in Project.objects.filter(is_active=True, status=Project.ACTIVE):
                raw = (request.POST.get(f"weight_{project.id}") or "").strip()
                try:
                    weight = int(raw) if raw else 0
                    if weight < 0:
                        weight = 0
                except (TypeError, ValueError):
                    weight = 0
                if project.serving_weight != weight:
                    project.serving_weight = weight
                    project.save(update_fields=["serving_weight"])
            messages.success(request, gettext("Manual weights saved."))

        elif action == "auto":
            for project in Project.objects.filter(is_active=True, status=Project.ACTIVE):
                raw = (request.POST.get(f"boost_{project.id}") or "").strip()
                try:
                    boost = float(raw) if raw else 1.0
                    if boost < 0:
                        boost = 0.0
                except (TypeError, ValueError):
                    boost = 1.0
                if project.serving_boost != boost:
                    project.serving_boost = boost
                    project.save(update_fields=["serving_boost"])
            messages.success(request, gettext("Boost multipliers saved."))

        return redirect("question_distribution")

    return render(
        request,
        "core/question_distribution.html",
        build_distribution_page_context(),
    )


def _accept_invite(token, invitee):
    if not token:
        return
    invite = Invite.objects.filter(
        token=token,
        accepted_at__isnull=True,
        invitee__isnull=True,
    ).first()
    if not invite:
        return
    if invite.inviter_id == invitee.id:
        return
    invite.accepted_at = timezone.now()
    invite.invitee = invitee
    invite.save(update_fields=["accepted_at", "invitee"])
