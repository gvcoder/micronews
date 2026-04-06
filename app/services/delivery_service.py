"""Delivery_Service: makes collected snippets available in each user's feed."""
import logging
from datetime import date, datetime, timezone, timedelta

from app import db, scheduler
from app.models.snippet import Snippet
from app.models.subscription import Subscription
from app.models.user_snippet import UserSnippet
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# IST is UTC+5:30 = 330 minutes ahead of UTC
_IST_OFFSET_MINUTES = 330

# Default delivery time: 10:00 IST = 04:30 UTC
_DEFAULT_UTC_HOUR = 4
_DEFAULT_UTC_MINUTE = 30


def _ist_to_utc(ist_time) -> tuple[int, int]:
    """Convert a time value in IST to (utc_hour, utc_minute).

    Handles day rollover (e.g. 00:00 IST → 18:30 UTC previous day,
    which maps to hour=18, minute=30 in a daily cron trigger).
    """
    total_minutes = ist_time.hour * 60 + ist_time.minute - _IST_OFFSET_MINUTES
    # Wrap into [0, 1440) range
    total_minutes = total_minutes % (24 * 60)
    return total_minutes // 60, total_minutes % 60


def schedule_delivery_job(user) -> None:
    """Schedule (or reschedule) the APScheduler delivery job for *user*.

    Converts user.preferred_delivery_time from IST to UTC.
    If preferred_delivery_time is None, defaults to 10:00 IST (04:30 UTC).

    Args:
        user: A User model instance.
    """
    if user.preferred_delivery_time is not None:
        utc_hour, utc_minute = _ist_to_utc(user.preferred_delivery_time)
    else:
        utc_hour, utc_minute = _DEFAULT_UTC_HOUR, _DEFAULT_UTC_MINUTE

    from app import scheduler as _scheduler

    # Import here to avoid circular imports at module load time
    from flask import current_app
    app = current_app._get_current_object()

    user_id = user.id

    def _deliver_with_context():
        with app.app_context():
            Delivery_Service().deliver_for_user(user_id)

    _scheduler.add_job(
        _deliver_with_context,
        trigger=CronTrigger(hour=utc_hour, minute=utc_minute, timezone='UTC'),
        id=f'delivery_{user.id}',
        replace_existing=True,
    )
    logger.info(
        'Scheduled delivery job for user %s at %02d:%02d UTC (from %s IST)',
        user.id,
        utc_hour,
        utc_minute,
        user.preferred_delivery_time,
    )


class Delivery_Service:
    """Makes collected snippets available in each user's in-app web feed."""

    def deliver_for_user(self, user_id: int) -> int:
        """Deliver undelivered snippets for *user_id*.

        Queries UserSnippet rows where:
          - user_id matches
          - delivered_at IS NULL
          - the associated Snippet.collection_date == today
          - the Snippet.category_id is in the user's subscribed categories

        Sets delivered_at = now() on all matching rows and returns the count.
        """
        today = date.today()
        now = datetime.now(timezone.utc)

        # Get the user's subscribed category IDs
        subscribed_category_ids = [
            row.category_id
            for row in Subscription.query.filter_by(user_id=user_id).all()
        ]

        if not subscribed_category_ids:
            return 0

        # Find undelivered UserSnippet rows for today's snippets in subscribed categories
        rows = (
            UserSnippet.query
            .join(Snippet, UserSnippet.snippet_id == Snippet.id)
            .filter(
                UserSnippet.user_id == user_id,
                UserSnippet.delivered_at.is_(None),
                Snippet.collection_date == today,
                Snippet.category_id.in_(subscribed_category_ids),
            )
            .all()
        )

        for row in rows:
            row.delivered_at = now

        if rows:
            db.session.commit()

        logger.info('Delivered %d snippets for user %s', len(rows), user_id)
        return len(rows)
