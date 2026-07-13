"""Email OTP helpers for login 2FA and worker password recovery."""

import hashlib
import secrets

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext

from .models import EmailOTP, User

OTP_LENGTH = 6
OTP_TTL_MINUTES = 10


def _hash_code(code):
    raw = f"{settings.SECRET_KEY}:{code}".encode()
    return hashlib.sha256(raw).hexdigest()


def generate_otp_code():
    upper = 10**OTP_LENGTH
    return str(secrets.randbelow(upper)).zfill(OTP_LENGTH)


def _otp_email_subject(purpose):
    if purpose == EmailOTP.PURPOSE_LOGIN:
        return gettext("Your CrowdLabel login code")
    if purpose == EmailOTP.PURPOSE_WORKER_SIGNUP:
        return gettext("Verify your CrowdLabel worker account")
    if purpose == EmailOTP.PURPOSE_CUSTOMER_SIGNUP:
        return gettext("Verify your CrowdLabel customer account")
    return gettext("Your CrowdLabel password reset code")


def _otp_email_body(code, purpose):
    if purpose == EmailOTP.PURPOSE_LOGIN:
        intro = gettext("Use this code to finish signing in to CrowdLabel:")
    elif purpose == EmailOTP.PURPOSE_WORKER_SIGNUP:
        intro = gettext("Use this code to verify your new CrowdLabel worker account:")
    elif purpose == EmailOTP.PURPOSE_CUSTOMER_SIGNUP:
        intro = gettext("Use this code to verify your new CrowdLabel customer account:")
    else:
        intro = gettext("Use this code to reset your CrowdLabel password:")
    return (
        f"{intro}\n\n"
        f"{code}\n\n"
        f"{gettext('This code expires in %(minutes)s minutes.') % {'minutes': OTP_TTL_MINUTES}}\n"
        f"{gettext('If you did not request this, you can ignore this email.')}"
    )


def create_and_send_otp(user, purpose):
    """Invalidate prior codes, create a new OTP, and email it to the user."""
    if not user.email:
        raise ValueError("User has no email address")

    EmailOTP.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(
        used_at=timezone.now()
    )

    code = generate_otp_code()
    expires_at = timezone.now() + timezone.timedelta(minutes=OTP_TTL_MINUTES)
    EmailOTP.objects.create(
        user=user,
        purpose=purpose,
        code_hash=_hash_code(code),
        expires_at=expires_at,
    )
    send_mail(
        subject=str(_otp_email_subject(purpose)),
        message=_otp_email_body(code, purpose),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    return code


def verify_otp(user, purpose, code):
    """Return True and mark the OTP used when the code matches."""
    code = (code or "").strip()
    if not code or not user:
        return False

    otp = (
        EmailOTP.objects.filter(
            user=user,
            purpose=purpose,
            used_at__isnull=True,
            expires_at__gte=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        return False
    if otp.code_hash != _hash_code(code):
        return False

    otp.used_at = timezone.now()
    otp.save(update_fields=["used_at"])
    return True


def roles_requiring_login_2fa():
    """Admins and customers use OTP on every login. Workers only verify email at signup."""
    return {User.ADMIN, User.CUSTOMER}


def roles_allowing_password_reset():
    """Roles that can self-recover via the emailed reset flow.

    Admins are excluded on purpose — they are seeded, not self-registered, and an
    operator resets them directly (management command / Django shell).
    """
    return {User.WORKER, User.CUSTOMER}


def normalize_email(raw):
    return (raw or "").strip().lower()


def is_valid_email_format(email):
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    try:
        validate_email(email)
    except ValidationError:
        return False
    return True


def email_taken(email, *, exclude_user_id=None):
    qs = User.objects.filter(email__iexact=email)
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()
