"""Password_Reset_Service: token generation, validation, and consumption."""
import secrets
import logging
from datetime import datetime, timezone, timedelta

from werkzeug.security import generate_password_hash

from app import db
from app.models.password_reset_token import PasswordResetToken
from app.models.email_verification_token import EmailVerificationToken
from app.services.email_service import send_email

logger = logging.getLogger(__name__)


class Password_Reset_Service:
    """Manages password-reset and email-verification token lifecycles."""

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    def send_reset_link(self, user) -> None:
        """Generate a secure token, persist it, and email the reset link.

        Args:
            user: A User model instance.
        """
        token_value = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        token = PasswordResetToken(
            user_id=user.id,
            token=token_value,
            expires_at=expires_at,
            used=False,
        )
        db.session.add(token)
        db.session.commit()

        reset_url = f"/reset-password/{token_value}"
        send_email(
            to=user.email,
            subject="Reset your Micro-News password",
            body=(
                f"Hi {user.name or user.email},\n\n"
                f"Click the link below to reset your password (valid for 1 hour):\n\n"
                f"{reset_url}\n\n"
                "If you did not request this, you can safely ignore this email."
            ),
        )

    def validate_token(self, token: str):
        """Return the associated User if the token is valid, else None.

        A token is valid when it exists, has not been used, and has not expired.
        """
        record = PasswordResetToken.query.filter_by(token=token).first()
        if record is None:
            return None
        if record.used:
            return None
        now = datetime.now(timezone.utc)
        expires = record.expires_at
        # Normalise to UTC-aware if stored as naive datetime
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            return None
        return record.user

    def consume_token(self, token: str, new_password: str) -> bool:
        """Hash and save the new password; mark the token as used.

        Returns True on success, False if the token is invalid/expired.
        """
        user = self.validate_token(token)
        if user is None:
            return False

        record = PasswordResetToken.query.filter_by(token=token).first()
        user.password_hash = generate_password_hash(new_password)
        record.used = True
        db.session.commit()
        return True

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    def send_verification_link(self, user) -> None:
        """Generate a 24-hour email verification token and send it.

        Args:
            user: A User model instance (newly registered).
        """
        token_value = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        token = EmailVerificationToken(
            user_id=user.id,
            token=token_value,
            expires_at=expires_at,
            used=False,
        )
        db.session.add(token)
        db.session.commit()

        verify_url = f"/verify/{token_value}"
        send_email(
            to=user.email,
            subject="Verify your Micro-News email address",
            body=(
                f"Hi {user.name or user.email},\n\n"
                f"Please verify your email address by clicking the link below "
                f"(valid for 24 hours):\n\n"
                f"{verify_url}\n\n"
                "If you did not create an account, you can safely ignore this email."
            ),
        )

    def consume_verification_token(self, token: str) -> bool:
        """Activate the user account associated with the verification token.

        Returns True on success, False if the token is invalid/expired/used.
        """
        record = EmailVerificationToken.query.filter_by(token=token).first()
        if record is None:
            return False
        if record.used:
            return False
        now = datetime.now(timezone.utc)
        expires = record.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= now:
            return False

        record.user.email_verified = True
        record.used = True
        db.session.commit()
        return True
