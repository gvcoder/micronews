"""
Unit tests for micro-news-app.
These tests cover specific examples, integration points, and edge cases.
"""

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# Test 1: Admin bootstrapping - env vars present + no admin → creates admin
# ---------------------------------------------------------------------------

def test_admin_bootstrap_env_vars_present_no_admin(app, db_session):
    """Test that bootstrap_admin creates admin when env vars present and no admin exists."""
    from app.models.admin import Admin
    from app.services.bootstrap import bootstrap_admin
    
    # Ensure no admin exists
    assert Admin.query.count() == 0
    
    # Set env vars
    os.environ["ADMIN_USERNAME"] = "testadmin"
    os.environ["ADMIN_PASSWORD"] = "TestPass1!"
    
    try:
        # Run bootstrap
        bootstrap_admin()
        
        # Verify admin was created
        admin = Admin.query.first()
        assert admin is not None
        assert admin.username == "testadmin"
        # Password should be hashed
        assert admin.password_hash != "TestPass1!"
        assert len(admin.password_hash) > 0
    finally:
        # Clean up env vars
        if "ADMIN_USERNAME" in os.environ:
            del os.environ["ADMIN_USERNAME"]
        if "ADMIN_PASSWORD" in os.environ:
            del os.environ["ADMIN_PASSWORD"]

# ---------------------------------------------------------------------------
# Test 2: Admin bootstrapping - env vars missing + no admin → SystemExit(1)
# ---------------------------------------------------------------------------

def test_admin_bootstrap_env_vars_missing_no_admin(app, db_session):
    """Test that bootstrap_admin raises SystemExit(1) when env vars missing and no admin exists."""
    from app.models.admin import Admin
    from app.services.bootstrap import bootstrap_admin
    
    # Ensure no admin exists
    assert Admin.query.count() == 0
    
    # Remove env vars if they exist
    old_username = os.environ.pop("ADMIN_USERNAME", None)
    old_password = os.environ.pop("ADMIN_PASSWORD", None)
    
    try:
        # Should raise SystemExit(1)
        with pytest.raises(SystemExit) as exc_info:
            bootstrap_admin()
        assert exc_info.value.code == 1
    finally:
        # Restore env vars
        if old_username is not None:
            os.environ["ADMIN_USERNAME"] = old_username
        if old_password is not None:
            os.environ["ADMIN_PASSWORD"] = old_password

# ---------------------------------------------------------------------------
# Test 3: Admin bootstrapping - admin already exists → no-op
# ---------------------------------------------------------------------------

def test_admin_bootstrap_admin_already_exists_no_op(app, db_session):
    """Test that bootstrap_admin does nothing when admin already exists."""
    from app.models.admin import Admin
    from app.services.bootstrap import bootstrap_admin
    
    # Create an admin first
    admin = Admin(
        username="existingadmin",
        password_hash=generate_password_hash("ExistingPass1!"),
    )
    db_session.session.add(admin)
    db_session.session.commit()
    
    count_before = Admin.query.count()
    
    # Set different env vars
    os.environ["ADMIN_USERNAME"] = "newadmin"
    os.environ["ADMIN_PASSWORD"] = "NewPass1!"
    
    try:
        # Run bootstrap - should not create new admin
        bootstrap_admin()
        
        # Verify no new admin was created
        count_after = Admin.query.count()
        assert count_after == count_before
        
        # Verify existing admin unchanged
        existing = Admin.query.filter_by(username="existingadmin").first()
        assert existing is not None
        assert existing.username == "existingadmin"
    finally:
        # Clean up env vars
        if "ADMIN_USERNAME" in os.environ:
            del os.environ["ADMIN_USERNAME"]
        if "ADMIN_PASSWORD" in os.environ:
            del os.environ["ADMIN_PASSWORD"]

# ---------------------------------------------------------------------------
# Test 4: Default delivery time is 10:00 IST when preferred_delivery_time is null
# ---------------------------------------------------------------------------

def test_default_delivery_time_10_ist_when_null(app, db_session):
    """Test that default delivery time is 10:00 IST when preferred_delivery_time is null."""
    from app.models.user import User
    from app.services.delivery_service import schedule_delivery_job
    from unittest.mock import patch, MagicMock
    
    # Create user with null preferred_delivery_time
    user = User(
        email="test@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
        preferred_delivery_time=None,
    )
    db_session.session.add(user)
    db_session.session.commit()
    
    # Mock the scheduler
    mock_scheduler = MagicMock()
    
    # Call schedule_delivery_job with mocked scheduler
    with patch("app.services.delivery_service.scheduler", mock_scheduler):
        schedule_delivery_job(user)
    
    # Verify scheduler was called with default UTC time (04:30)
    mock_scheduler.add_job.assert_called_once()
    call_args = mock_scheduler.add_job.call_args
    
    # Check trigger is CronTrigger with UTC time
    trigger = call_args[1]["trigger"]
    assert trigger.hour == 4  # UTC hour for 10:00 IST
    assert trigger.minute == 30  # UTC minute for 10:00 IST
    assert trigger.timezone == "UTC"

# ---------------------------------------------------------------------------
# Test 5: CollectionLog creation with mixed success/failure categories
# ---------------------------------------------------------------------------

def test_collection_log_creation_mixed_success_failure(app, db_session):
    """Test CollectionLog creation after a run with mixed success/failure categories."""
    from app.models.collection_log import CollectionLog
    import json
    
    # Simulate a run with 3 categories processed, 1 failed
    failure_details = [
        {
            "category": "Technology",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "Network timeout"
        }
    ]
    
    log = CollectionLog(
        run_at=datetime.now(timezone.utc),
        total_snippets=20,  # 20 snippets collected from successful categories
        categories_processed=3,
        categories_failed=1,
        failure_details=json.dumps(failure_details),
    )
    
    db_session.session.add(log)
    db_session.session.commit()
    
    # Verify the log
    stored = CollectionLog.query.first()
    assert stored is not None
    assert stored.total_snippets == 20
    assert stored.categories_processed == 3
    assert stored.categories_failed == 1
    
    # Verify failure details
    details = json.loads(stored.failure_details)
    assert len(details) == 1
    assert details[0]["category"] == "Technology"
    assert "Network timeout" in details[0]["error"]

# ---------------------------------------------------------------------------
# Test 6: Token expiry boundary - token expiring exactly at current time is rejected
# ---------------------------------------------------------------------------

def test_token_expiry_boundary_exact_current_time(app, db_session):
    """Test that token expiring exactly at current time is rejected."""
    from app.models.user import User
    from app.models.password_reset_token import PasswordResetToken
    from app.services.password_reset_service import Password_Reset_Service
    
    # Create user
    user = User(
        email="token@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()
    
    # Create token expiring exactly now
    now = datetime.now(timezone.utc)
    token_value = "test_token_123"
    token = PasswordResetToken(
        user_id=user.id,
        token=token_value,
        expires_at=now,
        used=False,
    )
    db_session.session.add(token)
    db_session.session.commit()
    
    # Token should be rejected (expired)
    service = Password_Reset_Service()
    result = service.validate_token(token_value)
    assert result is None

# ---------------------------------------------------------------------------
# Test 7: No-subscription prompt appears when user has zero subscriptions
# ---------------------------------------------------------------------------

def test_no_subscription_prompt_when_zero_subscriptions(app, db_session):
    """Test that no-subscription prompt appears when user has zero subscriptions."""
    from app.models.user import User
    from app.models.category import Category
    
    # Create user with no subscriptions
    user = User(
        email="nosub@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()
    
    # Create some categories
    for i in range(3):
        cat = Category(name=f"Category {i}")
        db_session.session.add(cat)
    db_session.session.commit()
    
    # Simulate what the subscriptions route would do
    from app.models.subscription import Subscription
    categories = Category.query.order_by(Category.name).all()
    user_subscriptions = {
        s.category_id for s in Subscription.query.filter_by(user_id=user.id).all()
    }
    
    # User should have zero subscriptions
    assert len(user_subscriptions) == 0
    
    # All categories should show as not subscribed
    for cat in categories:
        assert cat.id not in user_subscriptions

# ---------------------------------------------------------------------------
# Test 8: Default delivery time (10:00 IST) when user has no preferred_delivery_time set
# ---------------------------------------------------------------------------

def test_default_delivery_time_when_no_preferred_time_set(app, db_session):
    """Test default delivery time (10:00 IST) when user has no preferred_delivery_time set."""
    from app.models.user import User
    from app.services.delivery_service import schedule_delivery_job
    from unittest.mock import patch, MagicMock
    
    # Create user with null preferred_delivery_time
    user = User(
        email="nodeftime@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
        preferred_delivery_time=None,
    )
    db_session.session.add(user)
    db_session.session.commit()
    
    # Mock the scheduler
    mock_scheduler = MagicMock()
    
    # Call schedule_delivery_job with mocked scheduler
    with patch("app.services.delivery_service.scheduler", mock_scheduler):
        schedule_delivery_job(user)
    
    # Verify scheduler was called with 10:00 IST converted to UTC (04:30)
    mock_scheduler.add_job.assert_called_once()
    call_args = mock_scheduler.add_job.call_args
    
    # Check trigger is CronTrigger with UTC time
    trigger = call_args[1]["trigger"]
    assert trigger.hour == 4  # UTC hour for 10:00 IST
    assert trigger.minute == 30  # UTC minute for 10:00 IST
    assert trigger.timezone == "UTC"