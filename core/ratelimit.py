"""Cache-based request rate limiting."""

from __future__ import annotations

import hashlib
import time
from functools import wraps
from typing import Callable, NamedTuple

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils.translation import gettext


class RateLimitResult(NamedTuple):
    limited: bool
    retry_after: int = 0


DEFAULT_RATE_LIMITS = {
    # Auth — per IP unless noted
    "login_ip": (30, 900),
    "login_fail": (5, 900),
    "register": (10, 3600),
    "otp_send_ip": (10, 3600),
    "otp_send_user": (5, 3600),
    "otp_verify_fail": (5, 900),
    "forgot_password": (5, 3600),
    "forgot_password_email": (3, 3600),
    "reset_password": (10, 3600),
    # Authenticated actions
    "task_submit": (120, 60),
    "activity_month": (60, 60),
    "analytics": (30, 60),
    "csv_upload": (5, 3600),
    "store_buy": (20, 60),
    "invite_create": (10, 3600),
    "review_resolve": (60, 60),
}


def rate_limit_config(scope: str) -> tuple[int, int]:
    limits = getattr(settings, "RATE_LIMITS", DEFAULT_RATE_LIMITS)
    return limits.get(scope, DEFAULT_RATE_LIMITS[scope])


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "unknown")[:45]


def _key_part(value) -> str:
    if value is None or value == "":
        return "0"
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def rate_limit_key(scope: str, *parts) -> str:
    normalized = [_key_part(part) for part in parts]
    return f"rl:{scope}:" + ":".join(normalized)


def _read_record(key: str):
    record = cache.get(key)
    if not isinstance(record, dict):
        return None
    return record


def rate_limit_peek(scope: str, *parts, limit: int | None = None, window: int | None = None) -> RateLimitResult:
    """Check whether the limit is already exhausted without incrementing."""
    if limit is None or window is None:
        limit, window = rate_limit_config(scope)
    record = _read_record(rate_limit_key(scope, *parts))
    if record is None:
        return RateLimitResult(False, 0)
    elapsed = time.time() - record["start"]
    if elapsed >= window:
        return RateLimitResult(False, 0)
    if record["count"] >= limit:
        return RateLimitResult(True, max(1, int(window - elapsed) + 1))
    return RateLimitResult(False, 0)


def rate_limit_hit(scope: str, *parts, limit: int | None = None, window: int | None = None) -> RateLimitResult:
    """Increment the counter and report whether the limit is exceeded."""
    if limit is None or window is None:
        limit, window = rate_limit_config(scope)
    key = rate_limit_key(scope, *parts)
    now = time.time()
    record = _read_record(key)
    if record is None or (now - record["start"]) >= window:
        cache.set(key, {"count": 1, "start": now}, window)
        return RateLimitResult(False, 0)

    count = record["count"] + 1
    cache.set(key, {"count": count, "start": record["start"]}, window)
    if count > limit:
        retry_after = max(1, int(window - (now - record["start"])) + 1)
        return RateLimitResult(True, retry_after)
    return RateLimitResult(False, 0)


def rate_limit_clear(scope: str, *parts) -> None:
    cache.delete(rate_limit_key(scope, *parts))


def too_many_requests_message(retry_after: int) -> str:
    if retry_after > 0:
        return gettext(
            "Too many requests. Please wait %(seconds)s seconds and try again."
        ) % {"seconds": retry_after}
    return gettext("Too many requests. Please try again later.")


def rate_limit_response(request, result: RateLimitResult, *, as_json: bool = False):
    message = too_many_requests_message(result.retry_after)
    if as_json:
        return JsonResponse({"error": message}, status=429)
    return HttpResponse(message, status=429, content_type="text/plain; charset=utf-8")


def guard_otp_send(request, user) -> RateLimitResult | None:
    """Return a RateLimitResult when OTP email send should be blocked."""
    ip_result = rate_limit_peek("otp_send_ip", client_ip(request))
    if ip_result.limited:
        return ip_result
    user_result = rate_limit_peek("otp_send_user", user.id)
    if user_result.limited:
        return user_result
    ip_hit = rate_limit_hit("otp_send_ip", client_ip(request))
    if ip_hit.limited:
        return ip_hit
    user_hit = rate_limit_hit("otp_send_user", user.id)
    if user_hit.limited:
        return user_hit
    return None


def guard_otp_verify(request, user) -> RateLimitResult | None:
    result = rate_limit_peek("otp_verify_fail", client_ip(request), user.id)
    return result if result.limited else None


def record_otp_verify_failure(request, user) -> RateLimitResult:
    return rate_limit_hit("otp_verify_fail", client_ip(request), user.id)


def clear_otp_verify_failures(request, user) -> None:
    rate_limit_clear("otp_verify_fail", client_ip(request), user.id)


def rate_limit(
    scope: str,
    *,
    methods: tuple[str, ...] = ("POST",),
    key_parts: Callable | None = None,
    as_json: bool = False,
):
    """Decorator for views that should be throttled on matching HTTP methods."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return view(request, *args, **kwargs)
            parts = [client_ip(request)]
            if request.user.is_authenticated:
                parts.append(request.user.pk)
            if key_parts is not None:
                parts.extend(key_parts(request, *args, **kwargs))
            result = rate_limit_hit(scope, *parts)
            if result.limited:
                return rate_limit_response(request, result, as_json=as_json)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
