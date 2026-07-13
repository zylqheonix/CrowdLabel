"""Small security helpers shared across views."""

from django.contrib.auth import SESSION_KEY
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.utils.http import url_has_allowed_host_and_scheme


def password_error(password, *, user=None):
    """Run the project's configured AUTH_PASSWORD_VALIDATORS on a new password.

    Returns a single human-readable error string when the password is rejected,
    or None when it passes. Every entry point that sets a user-chosen password
    (registration, password reset, password change) routes through this so they
    all enforce the same rules — minimum length, the common-password blocklist,
    numeric-only rejection, and similarity to the account's username/email.

    Pass ``user`` (saved or unsaved) so the similarity check can compare against
    that account's attributes.
    """
    try:
        validate_password(password or "", user=user)
    except ValidationError as exc:
        return " ".join(exc.messages)
    return None


def safe_next_url(request, candidate, fallback):
    """Allow only same-host relative/absolute redirects; otherwise use fallback."""
    candidate = (candidate or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def invalidate_user_sessions(user, *, keep_session_key=None):
    """Delete all stored sessions authenticated as this user."""
    user_id = str(user.pk)
    for session in Session.objects.all().iterator():
        if keep_session_key and session.session_key == keep_session_key:
            continue
        try:
            data = session.get_decoded()
        except Exception:
            session.delete()
            continue
        if data.get(SESSION_KEY) == user_id:
            session.delete()
