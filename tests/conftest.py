"""
Pytest fixtures for micro-news-app property-based tests.

Each database-touching test gets a fresh in-memory SQLite instance via the
`db_session` fixture.  The Flask app is created with TestingConfig and admin
bootstrapping is patched out so no SystemExit(1) is raised.
"""

import os
import pytest
from unittest.mock import patch

# Provide dummy env vars so bootstrap_admin() doesn't raise SystemExit(1)
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "TestPass1!")


@pytest.fixture(scope="session")
def app():
    """Create the Flask application configured for testing (session-scoped)."""
    # Patch bootstrap_admin to a no-op so the app factory never calls SystemExit
    with patch("app.services.bootstrap.bootstrap_admin", return_value=None):
        from app import create_app
        flask_app = create_app("testing")

    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        # Disable APScheduler during tests
        SCHEDULER_API_ENABLED=False,
    )
    return flask_app


@pytest.fixture(scope="session")
def client(app):
    """Return a Flask test client (session-scoped)."""
    return app.test_client()


@pytest.fixture(autouse=False)
def db_session(app):
    """
    Provide a clean database for each test.

    Creates all tables before the test and drops them afterwards so every
    property-based test iteration starts from an empty schema.
    """
    from app import db as _db

    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()
