"""
Admin account bootstrapping (task 3.6).

Called once at application startup inside the app context.
- If an Admin already exists → no-op.
- If no Admin exists and env vars are set → create the account.
- If no Admin exists and env vars are missing → log CRITICAL and raise SystemExit(1).
"""

import logging
import os

from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)


def bootstrap_admin() -> None:
    """Create the first Admin account from environment variables if none exists."""
    from app.models.admin import Admin
    from app import db

    if Admin.query.first() is not None:
        logger.info("Admin account already exists – skipping bootstrap.")
        return

    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")

    if not username or not password:
        logger.critical(
            "No Admin account found and ADMIN_USERNAME / ADMIN_PASSWORD "
            "environment variables are not set. Cannot start the application."
        )
        raise SystemExit(1)

    admin = Admin(
        username=username,
        password_hash=generate_password_hash(password),
    )
    db.session.add(admin)
    db.session.commit()
    logger.info("Bootstrap: Admin account '%s' created successfully.", username)
