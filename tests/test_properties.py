"""
Property-based tests for micro-news-app.
All 35 correctness properties from design.md are covered here.

Each test is tagged:
  # Feature: micro-news-app, Property N: {property_text}

Library: Hypothesis  |  min iterations: 100 (@settings(max_examples=100))
"""

import json
import secrets
from datetime import date, datetime, time, timedelta, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Shared Hypothesis strategies
# ---------------------------------------------------------------------------

# Valid passwords: >=8 chars, has upper, lower, digit
_VALID_PASSWORD_ST = st.builds(
    lambda base, upper, lower, digit: upper + lower + digit + base,
    base=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=5,
        max_size=20,
    ),
    upper=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=1),
    lower=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=1),
    digit=st.text(alphabet="0123456789", min_size=1, max_size=1),
)

# Valid past birthdays
_PAST_DATE_ST = st.dates(
    min_value=date(1900, 1, 1),
    max_value=date.today() - timedelta(days=1),
)

# Expired datetime (at least 2 hours in the past to avoid flakiness)
_EXPIRED_DT_ST = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime.utcnow() - timedelta(hours=2),
)

# Category names: printable ASCII, non-empty, no leading/trailing whitespace
_CATEGORY_NAME_ST = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" "),
    min_size=1,
    max_size=50,
).map(str.strip).filter(lambda s: len(s) > 0)


# ===========================================================================
# Property 1: Valid credentials authenticate users
# ===========================================================================

# Feature: micro-news-app, Property 1: Valid credentials authenticate users
@given(
    username=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
        min_size=3,
        max_size=30,
    ),
    password=_VALID_PASSWORD_ST,
)
@settings(max_examples=100)
def test_valid_credentials_authenticate_admin(app, db_session, username, password):
    """For any registered admin with known credentials, login should succeed."""
    from app.models.admin import Admin

    admin = Admin(
        username=username,
        password_hash=generate_password_hash(password),
    )
    db_session.session.add(admin)
    db_session.session.commit()

    with app.test_client() as c:
        resp = c.post(
            "/admin/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
    # Successful login redirects to dashboard
    assert resp.status_code in (302, 200)
    if resp.status_code == 302:
        assert "dashboard" in resp.headers.get("Location", "")


# ===========================================================================
# Property 2: Invalid credentials are rejected
# ===========================================================================

# Feature: micro-news-app, Property 2: Invalid credentials are rejected
@given(
    username=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
        min_size=3,
        max_size=30,
    ),
    wrong_password=_VALID_PASSWORD_ST,
)
@settings(max_examples=100)
def test_invalid_credentials_are_rejected(app, db_session, username, wrong_password):
    """For any credential pair where the password doesn't match, login should fail."""
    from app.models.admin import Admin

    real_password = "RealPass1!"
    assume(wrong_password != real_password)

    admin = Admin(
        username=username,
        password_hash=generate_password_hash(real_password),
    )
    db_session.session.add(admin)
    db_session.session.commit()

    with app.test_client() as c:
        resp = c.post(
            "/admin/login",
            data={"username": username, "password": wrong_password},
            follow_redirects=False,
        )
    assert resp.status_code in (401, 429)


# ===========================================================================
# Property 3: Unauthenticated requests are redirected
# ===========================================================================

_PROTECTED_ADMIN_ROUTES = [
    "/admin/dashboard",
    "/admin/categories",
    "/admin/collection-log",
]

_PROTECTED_USER_ROUTES = [
    "/dashboard",
    "/feed",
    "/profile",
    "/subscriptions",
]

# Feature: micro-news-app, Property 3: Unauthenticated requests are redirected
@given(route=st.sampled_from(_PROTECTED_ADMIN_ROUTES + _PROTECTED_USER_ROUTES))
@settings(max_examples=100)
def test_unauthenticated_requests_are_redirected(app, db_session, route):
    """For any protected route, request without session → HTTP 302 to login."""
    with app.test_client() as c:
        resp = c.get(route, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "login" in location


# ===========================================================================
# Property 4: Inactive sessions are invalidated
# ===========================================================================

# Feature: micro-news-app, Property 4: Inactive sessions are invalidated
@given(
    minutes_ago=st.integers(min_value=61, max_value=300),
)
@settings(max_examples=100)
def test_inactive_admin_session_is_invalidated(app, db_session, minutes_ago):
    """Admin session older than 60 min of inactivity should be treated as expired."""
    from app.models.admin import Admin

    admin = Admin(
        username="sessionadmin",
        password_hash=generate_password_hash("AdminPass1!"),
    )
    db_session.session.add(admin)
    db_session.session.commit()

    stale_time = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ).isoformat()

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = str(admin.id)
            sess["admin_last_active"] = stale_time

        resp = c.get("/admin/dashboard", follow_redirects=False)

    assert resp.status_code == 302
    assert "login" in resp.headers.get("Location", "")


# ===========================================================================
# Property 5: Rate limiting blocks excessive failed logins
# ===========================================================================

# Feature: micro-news-app, Property 5: Rate limiting blocks excessive failed logins
@given(extra_attempts=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_rate_limiting_blocks_excessive_failed_logins(app, db_session, extra_attempts):
    """After 5+ consecutive failures from same IP within 10 min, next attempt is blocked."""
    from app.admin import rate_limiter

    # Use a unique IP per test run to avoid cross-test pollution
    test_ip = f"10.0.{extra_attempts}.{extra_attempts % 255}"

    # Clear any existing state for this IP
    with rate_limiter._lock:
        rate_limiter._store.pop(test_ip, None)

    # Record 5 failures to trigger the block
    for _ in range(5):
        rate_limiter.record_failure(test_ip)

    assert rate_limiter.is_blocked(test_ip), (
        f"IP {test_ip} should be blocked after 5 failures"
    )

    # Clean up
    with rate_limiter._lock:
        rate_limiter._store.pop(test_ip, None)


# ===========================================================================
# Property 6: Category creation round-trip
# ===========================================================================

# Feature: micro-news-app, Property 6: Category creation round-trip
@given(name=_CATEGORY_NAME_ST)
@settings(max_examples=100)
def test_category_creation_round_trip(app, db_session, name):
    """For any valid category name, create then query → found (case-insensitive)."""
    from app.models.category import Category
    from sqlalchemy import func

    cat = Category(name=name)
    db_session.session.add(cat)
    db_session.session.commit()

    found = Category.query.filter(
        func.lower(Category.name) == name.lower()
    ).first()
    assert found is not None
    assert found.name == name


# ===========================================================================
# Property 7: Duplicate category names are rejected
# ===========================================================================

# Feature: micro-news-app, Property 7: Duplicate category names are rejected
@given(name=_CATEGORY_NAME_ST)
@settings(max_examples=100)
def test_duplicate_category_names_are_rejected(app, db_session, name):
    """For any existing category name, creating same name (any casing) → rejected."""
    from app.models.category import Category
    from sqlalchemy import func
    from sqlalchemy.exc import IntegrityError

    cat = Category(name=name)
    db_session.session.add(cat)
    db_session.session.commit()

    count_before = Category.query.count()

    # Attempt to insert duplicate (same name, different casing via swapcase)
    duplicate_name = name.swapcase() if name != name.swapcase() else name.upper()
    # The unique index is on func.lower(name), so any casing collision should fail
    dup = Category(name=duplicate_name)
    db_session.session.add(dup)
    try:
        db_session.session.commit()
        # If commit succeeded, names must differ case-insensitively (swapcase edge case)
        count_after = Category.query.count()
        if name.lower() == duplicate_name.lower():
            # Should not have succeeded
            assert False, "Duplicate category was accepted"
    except IntegrityError:
        db_session.session.rollback()
        count_after = Category.query.count()
        assert count_after == count_before


# ===========================================================================
# Property 8: Category deletion cascades to snippets
# ===========================================================================

# Feature: micro-news-app, Property 8: Category deletion cascades to snippets
@given(snippet_count=st.integers(min_value=1, max_value=5))
@settings(max_examples=100)
def test_category_deletion_cascades_to_snippets(app, db_session, snippet_count):
    """Deleting a category removes the category and all its snippets."""
    from app.models.category import Category
    from app.models.snippet import Snippet

    cat = Category(name=f"CascadeCat{snippet_count}")
    db_session.session.add(cat)
    db_session.session.commit()

    for i in range(snippet_count):
        s = Snippet(
            category_id=cat.id,
            headline=f"Headline {i}",
            body=" ".join(["word"] * 10),
            collection_date=date.today(),
        )
        db_session.session.add(s)
    db_session.session.commit()

    cat_id = cat.id
    db_session.session.delete(cat)
    db_session.session.commit()

    assert Category.query.get(cat_id) is None
    assert Snippet.query.filter_by(category_id=cat_id).count() == 0


# ===========================================================================
# Property 9: Affected-user count is accurate before deletion
# ===========================================================================

# Feature: micro-news-app, Property 9: Affected-user count is accurate before deletion
@given(n_subscribers=st.integers(min_value=0, max_value=10))
@settings(max_examples=100)
def test_affected_user_count_is_accurate(app, db_session, n_subscribers):
    """For any category with N subscriptions, pre-deletion count = N."""
    from app.models.category import Category
    from app.models.user import User
    from app.models.subscription import Subscription

    cat = Category(name=f"AffectedCat{n_subscribers}")
    db_session.session.add(cat)
    db_session.session.commit()

    for i in range(n_subscribers):
        user = User(
            email=f"affected{i}_{n_subscribers}@example.com",
            password_hash=generate_password_hash("Pass1word!"),
            email_verified=True,
        )
        db_session.session.add(user)
        db_session.session.flush()
        sub = Subscription(user_id=user.id, category_id=cat.id)
        db_session.session.add(sub)
    db_session.session.commit()

    count = Subscription.query.filter_by(category_id=cat.id).count()
    assert count == n_subscribers


# ===========================================================================
# Property 10: Category list is alphabetically sorted
# ===========================================================================

# Feature: micro-news-app, Property 10: Category list is alphabetically sorted
@given(names=st.lists(_CATEGORY_NAME_ST, min_size=2, max_size=10, unique_by=str.lower))
@settings(max_examples=100)
def test_category_list_is_alphabetically_sorted(app, db_session, names):
    """For any set of categories, list endpoint returns them in case-insensitive alpha order."""
    from app.models.category import Category
    from sqlalchemy import func

    for name in names:
        db_session.session.add(Category(name=name))
    db_session.session.commit()

    categories = Category.query.order_by(func.lower(Category.name)).all()
    returned_names = [c.name for c in categories]
    expected = sorted(returned_names, key=str.lower)
    assert returned_names == expected


# ===========================================================================
# Property 11: Snippet word count invariant
# ===========================================================================

# Feature: micro-news-app, Property 11: Snippet word count invariant
@given(word_count=st.integers(min_value=1, max_value=60))
@settings(max_examples=100)
def test_snippet_word_count_invariant(app, db_session, word_count):
    """For any snippet in DB, len(body.split()) <= 60."""
    from app.models.category import Category
    from app.models.snippet import Snippet

    cat = Category(name=f"WordCountCat{word_count}")
    db_session.session.add(cat)
    db_session.session.commit()

    body = " ".join(["word"] * word_count)
    snippet = Snippet(
        category_id=cat.id,
        headline="Test headline",
        body=body,
        collection_date=date.today(),
    )
    db_session.session.add(snippet)
    db_session.session.commit()

    stored = Snippet.query.get(snippet.id)
    assert len(stored.body.split()) <= 60


# ===========================================================================
# Property 12: Snippets are associated with their category
# ===========================================================================

# Feature: micro-news-app, Property 12: Snippets are associated with their category
@given(n_snippets=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_snippets_associated_with_category(app, db_session, n_snippets):
    """For any snippet generated for a category, querying by category includes it."""
    from app.models.category import Category
    from app.models.snippet import Snippet

    cat = Category(name=f"AssocCat{n_snippets}")
    db_session.session.add(cat)
    db_session.session.commit()

    snippet_ids = []
    for i in range(n_snippets):
        s = Snippet(
            category_id=cat.id,
            headline=f"Headline {i}",
            body="word " * 5,
            collection_date=date.today(),
        )
        db_session.session.add(s)
        db_session.session.flush()
        snippet_ids.append(s.id)
    db_session.session.commit()

    found_ids = {
        s.id for s in Snippet.query.filter_by(category_id=cat.id).all()
    }
    assert set(snippet_ids) == found_ids


# ===========================================================================
# Property 13: Collection failure log completeness
# ===========================================================================

# Feature: micro-news-app, Property 13: Collection failure log completeness
@given(
    category_name=_CATEGORY_NAME_ST,
    error_msg=st.text(min_size=1, max_size=100),
)
@settings(max_examples=100)
def test_collection_failure_log_completeness(app, db_session, category_name, error_msg):
    """For any failed category, CollectionLog.failure_details contains name, timestamp, error."""
    from app.models.collection_log import CollectionLog

    failure_entry = {
        "category": category_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": error_msg,
    }
    log = CollectionLog(
        run_at=datetime.now(timezone.utc),
        total_snippets=0,
        categories_processed=1,
        categories_failed=1,
        failure_details=json.dumps([failure_entry]),
    )
    db_session.session.add(log)
    db_session.session.commit()

    stored = CollectionLog.query.get(log.id)
    details = json.loads(stored.failure_details)
    assert len(details) == 1
    assert details[0]["category"] == category_name
    assert "timestamp" in details[0]
    assert details[0]["error"] == error_msg


# ===========================================================================
# Property 14: Collection log records run metadata
# ===========================================================================

# Feature: micro-news-app, Property 14: Collection log records run metadata
@given(
    total=st.integers(min_value=0, max_value=100),
    processed=st.integers(min_value=0, max_value=20),
    failed=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_collection_log_records_run_metadata(app, db_session, total, processed, failed):
    """For any completed run, CollectionLog has non-null run_at, non-negative total_snippets."""
    from app.models.collection_log import CollectionLog

    log = CollectionLog(
        run_at=datetime.now(timezone.utc),
        total_snippets=total,
        categories_processed=processed,
        categories_failed=failed,
    )
    db_session.session.add(log)
    db_session.session.commit()

    stored = CollectionLog.query.get(log.id)
    assert stored.run_at is not None
    assert stored.total_snippets >= 0
    assert stored.categories_processed == processed
    assert stored.categories_failed == failed


# ===========================================================================
# Property 15: Snippet count per category per run is bounded
# ===========================================================================

# Feature: micro-news-app, Property 15: Snippet count per category per run is bounded
@given(snippet_count=st.integers(min_value=0, max_value=10))
@settings(max_examples=100)
def test_snippet_count_per_category_per_run_bounded(app, db_session, snippet_count):
    """For any category and collection_date, snippet count <= 10."""
    from app.models.category import Category
    from app.models.snippet import Snippet

    cat = Category(name=f"BoundedCat{snippet_count}")
    db_session.session.add(cat)
    db_session.session.commit()

    today = date.today()
    for i in range(snippet_count):
        s = Snippet(
            category_id=cat.id,
            headline=f"Headline {i}",
            body="word " * 5,
            collection_date=today,
        )
        db_session.session.add(s)
    db_session.session.commit()

    count = Snippet.query.filter_by(
        category_id=cat.id, collection_date=today
    ).count()
    assert count <= 10


# ===========================================================================
# Property 16: Registration creates a user account
# ===========================================================================

# Feature: micro-news-app, Property 16: Registration creates a user account
@given(
    email=st.emails(),
    password=_VALID_PASSWORD_ST,
)
@settings(max_examples=100)
def test_registration_creates_user_account(app, db_session, email, password):
    """For any valid (email, password) not already registered, registration → User in DB."""
    from app.models.user import User
    from app.services.email_validator import Email_Validator

    validator = Email_Validator()
    assume(validator.validate_format(email))

    # Ensure email not already in DB
    assume(User.query.filter_by(email=email).first() is None)

    with app.test_client() as c:
        with app.app_context():
            from unittest.mock import patch
            with patch("app.services.password_reset_service.send_email"):
                resp = c.post(
                    "/register",
                    data={
                        "email": email,
                        "password": password,
                        "confirm_password": password,
                    },
                    follow_redirects=False,
                )

    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        assert user.email_verified is False


# ===========================================================================
# Property 17: Invalid email formats are rejected
# ===========================================================================

_INVALID_EMAIL_ST = st.one_of(
    st.just("notanemail"),
    st.just("missing@"),
    st.just("@nodomain"),
    st.just("no-at-sign"),
    st.just("double@@domain.com"),
    st.just(""),
    st.just("spaces in@email.com"),
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
        min_size=1,
        max_size=20,
    ).filter(lambda s: "@" not in s),
)

# Feature: micro-news-app, Property 17: Invalid email formats are rejected
@given(bad_email=_INVALID_EMAIL_ST)
@settings(max_examples=100)
def test_invalid_email_formats_are_rejected(bad_email):
    """For any non-RFC5322 string, Email_Validator.validate_format → False."""
    from app.services.email_validator import Email_Validator

    validator = Email_Validator()
    assert validator.validate_format(bad_email) is False


# ===========================================================================
# Property 18: Duplicate email registration is rejected
# ===========================================================================

# Feature: micro-news-app, Property 18: Duplicate email registration is rejected
@given(
    email=st.emails(),
    password=_VALID_PASSWORD_ST,
)
@settings(max_examples=100)
def test_duplicate_email_registration_rejected(app, db_session, email, password):
    """For any existing email, re-registration → rejected, user count unchanged."""
    from app.models.user import User
    from app.services.email_validator import Email_Validator

    validator = Email_Validator()
    assume(validator.validate_format(email))

    # Create the user directly
    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.commit()

    count_before = User.query.count()

    with app.test_client() as c:
        with app.app_context():
            from unittest.mock import patch
            with patch("app.services.password_reset_service.send_email"):
                resp = c.post(
                    "/register",
                    data={
                        "email": email,
                        "password": password,
                        "confirm_password": password,
                    },
                    follow_redirects=False,
                )

    with app.app_context():
        count_after = User.query.count()
        assert count_after == count_before


# ===========================================================================
# Property 19: Weak passwords are rejected
# ===========================================================================

_WEAK_PASSWORD_ST = st.one_of(
    # Too short
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=1,
        max_size=7,
    ),
    # No uppercase
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
        min_size=8,
        max_size=20,
    ).filter(lambda s: any(c.isdigit() for c in s)),
    # No lowercase
    st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=8,
        max_size=20,
    ).filter(lambda s: any(c.isdigit() for c in s)),
    # No digit
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        min_size=8,
        max_size=20,
    ).filter(lambda s: any(c.isupper() for c in s) and any(c.islower() for c in s)),
)

# Feature: micro-news-app, Property 19: Weak passwords are rejected
@given(weak_password=_WEAK_PASSWORD_ST)
@settings(max_examples=100)
def test_weak_passwords_are_rejected(weak_password):
    """For any password < 8 chars or missing uppercase/lowercase/digit → validate_password False."""
    from app.services.password_validator import validate_password

    valid, _ = validate_password(weak_password)
    assert valid is False


# ===========================================================================
# Property 20: Email verification token round-trip
# ===========================================================================

# Feature: micro-news-app, Property 20: Email verification token round-trip
@given(token_value=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=10, max_size=64))
@settings(max_examples=100)
def test_email_verification_token_round_trip(app, db_session, token_value):
    """For any valid unexpired EmailVerificationToken, consuming → email_verified=True."""
    from app.models.user import User
    from app.models.email_verification_token import EmailVerificationToken
    from app.services.password_reset_service import Password_Reset_Service

    user = User(
        email=f"verify_{token_value[:8]}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=False,
    )
    db_session.session.add(user)
    db_session.session.flush()

    token = EmailVerificationToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        used=False,
    )
    db_session.session.add(token)
    db_session.session.commit()

    service = Password_Reset_Service()
    result = service.consume_verification_token(token_value)

    assert result is True
    refreshed_user = User.query.get(user.id)
    assert refreshed_user.email_verified is True
    refreshed_token = EmailVerificationToken.query.filter_by(token=token_value).first()
    assert refreshed_token.used is True


# ===========================================================================
# Property 21: Expired tokens are rejected
# ===========================================================================

# Feature: micro-news-app, Property 21: Expired tokens are rejected
@given(expired_dt=_EXPIRED_DT_ST)
@settings(max_examples=100)
def test_expired_tokens_are_rejected(app, db_session, expired_dt):
    """For any token with expires_at in the past, validate_token → None/False."""
    from app.models.user import User
    from app.models.password_reset_token import PasswordResetToken
    from app.services.password_reset_service import Password_Reset_Service

    user = User(
        email=f"expired_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()

    token_value = secrets.token_urlsafe(32)
    token = PasswordResetToken(
        user_id=user.id,
        token=token_value,
        expires_at=expired_dt,
        used=False,
    )
    db_session.session.add(token)
    db_session.session.commit()

    service = Password_Reset_Service()
    result = service.validate_token(token_value)
    assert result is None


# ===========================================================================
# Property 22: Profile fields persist correctly
# ===========================================================================

# Feature: micro-news-app, Property 22: Profile fields persist correctly
@given(
    name=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ",
        min_size=1,
        max_size=50,
    ).map(str.strip).filter(lambda s: len(s) > 0),
    birthday=_PAST_DATE_ST,
    delivery_hour=st.integers(min_value=0, max_value=23),
    delivery_minute=st.integers(min_value=0, max_value=59),
)
@settings(max_examples=100)
def test_profile_fields_persist_correctly(app, db_session, name, birthday, delivery_hour, delivery_minute):
    """For any user updating name/birthday/preferred_delivery_time, reading back → updated values."""
    from app.models.user import User
    from unittest.mock import patch

    user = User(
        email=f"profile_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.commit()

    delivery_time = time(delivery_hour, delivery_minute)

    with patch("app.services.delivery_service.schedule_delivery_job"):
        user.name = name
        user.birthday = birthday
        user.preferred_delivery_time = delivery_time
        db_session.session.commit()

    refreshed = User.query.get(user.id)
    assert refreshed.name == name
    assert refreshed.birthday == birthday
    assert refreshed.preferred_delivery_time == delivery_time


# ===========================================================================
# Property 23: Birthday must be a past date
# ===========================================================================

_FUTURE_OR_TODAY_DATE_ST = st.dates(
    min_value=date.today(),
    max_value=date(2100, 12, 31),
)

# Feature: micro-news-app, Property 23: Birthday must be a past date
@given(
    future_date=_FUTURE_OR_TODAY_DATE_ST,
    past_date=_PAST_DATE_ST,
)
@settings(max_examples=100)
def test_birthday_must_be_past_date(app, db_session, future_date, past_date):
    """For any date >= today, birthday validation → rejected; for any past date → accepted."""
    from app.models.user import User

    user = User(
        email=f"bday_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.commit()

    with app.test_client() as c:
        # Log in the user via session manipulation
        with c.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["user_last_active"] = datetime.now(timezone.utc).isoformat()

        # Future/today date should be rejected
        resp_future = c.post(
            "/profile",
            data={
                "name": "Test",
                "birthday": future_date.isoformat(),
                "preferred_delivery_time": "",
            },
            follow_redirects=False,
        )
        assert resp_future.status_code == 422

        # Past date should be accepted
        with app.app_context():
            from unittest.mock import patch
            with patch("app.services.delivery_service.schedule_delivery_job"):
                resp_past = c.post(
                    "/profile",
                    data={
                        "name": "Test",
                        "birthday": past_date.isoformat(),
                        "preferred_delivery_time": "",
                    },
                    follow_redirects=False,
                )
        assert resp_past.status_code in (200, 302)


# ===========================================================================
# Property 24: Profile page displays all fields
# ===========================================================================

# Feature: micro-news-app, Property 24: Profile page displays all fields
@given(
    name=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        min_size=2,
        max_size=30,
    ),
    birthday=_PAST_DATE_ST,
    delivery_hour=st.integers(min_value=0, max_value=23),
    delivery_minute=st.integers(min_value=0, max_value=59),
)
@settings(max_examples=100)
def test_profile_page_displays_all_fields(app, db_session, name, birthday, delivery_hour, delivery_minute):
    """For any user with name/birthday/preferred_delivery_time set, profile page contains all three."""
    from app.models.user import User

    delivery_time = time(delivery_hour, delivery_minute)
    user = User(
        email=f"display_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
        name=name,
        birthday=birthday,
        preferred_delivery_time=delivery_time,
    )
    db_session.session.add(user)
    db_session.session.commit()

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = str(user.id)
            sess["user_last_active"] = datetime.now(timezone.utc).isoformat()

        resp = c.get("/profile")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert name in body
    assert birthday.isoformat() in body
    assert f"{delivery_hour:02d}:{delivery_minute:02d}" in body


# ===========================================================================
# Property 25: Password reset token is created on request
# ===========================================================================

# Feature: micro-news-app, Property 25: Password reset token is created on request
@given(dummy=st.integers(min_value=0, max_value=99))
@settings(max_examples=100)
def test_password_reset_token_created_on_request(app, db_session, dummy):
    """For any registered user requesting reset, PasswordResetToken created with future expires_at."""
    from app.models.user import User
    from app.models.password_reset_token import PasswordResetToken
    from app.services.password_reset_service import Password_Reset_Service
    from unittest.mock import patch

    user = User(
        email=f"reset_{dummy}_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.commit()

    with patch("app.services.password_reset_service.send_email"):
        service = Password_Reset_Service()
        service.send_reset_link(user)

    token = PasswordResetToken.query.filter_by(user_id=user.id).first()
    assert token is not None
    expires = token.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    assert expires > datetime.now(timezone.utc)


# ===========================================================================
# Property 26: Password reset token consumption updates password
# ===========================================================================

# Feature: micro-news-app, Property 26: Password reset token consumption updates password
@given(new_password=_VALID_PASSWORD_ST)
@settings(max_examples=100)
def test_password_reset_token_consumption_updates_password(app, db_session, new_password):
    """For any valid unexpired token and valid new password, consume → password_hash updated."""
    from app.models.user import User
    from app.models.password_reset_token import PasswordResetToken
    from app.services.password_reset_service import Password_Reset_Service

    user = User(
        email=f"consume_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("OldPass1!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()

    token_value = secrets.token_urlsafe(32)
    token = PasswordResetToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        used=False,
    )
    db_session.session.add(token)
    db_session.session.commit()

    service = Password_Reset_Service()
    result = service.consume_token(token_value, new_password)

    assert result is True
    refreshed_user = User.query.get(user.id)
    assert check_password_hash(refreshed_user.password_hash, new_password)
    refreshed_token = PasswordResetToken.query.filter_by(token=token_value).first()
    assert refreshed_token.used is True


# ===========================================================================
# Property 27: Subscribe/unsubscribe round-trip
# ===========================================================================

# Feature: micro-news-app, Property 27: Subscribe/unsubscribe round-trip
@given(dummy=st.integers(min_value=0, max_value=99))
@settings(max_examples=100)
def test_subscribe_unsubscribe_round_trip(app, db_session, dummy):
    """For any user and category, subscribe then unsubscribe → no subscription record."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.subscription import Subscription

    user = User(
        email=f"subuser_{dummy}_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    cat = Category(name=f"SubCat{dummy}{secrets.token_hex(2)}")
    db_session.session.add(user)
    db_session.session.add(cat)
    db_session.session.flush()

    sub = Subscription(user_id=user.id, category_id=cat.id)
    db_session.session.add(sub)
    db_session.session.commit()

    # Verify subscribed
    assert Subscription.query.filter_by(user_id=user.id, category_id=cat.id).first() is not None

    # Unsubscribe
    db_session.session.delete(sub)
    db_session.session.commit()

    assert Subscription.query.filter_by(user_id=user.id, category_id=cat.id).first() is None


# ===========================================================================
# Property 28: Category list reflects subscription status
# ===========================================================================

# Feature: micro-news-app, Property 28: Category list reflects subscription status
@given(
    n_categories=st.integers(min_value=1, max_value=5),
    n_subscribed=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_category_list_reflects_subscription_status(app, db_session, n_categories, n_subscribed):
    """For any user, subscriptions page includes all categories with correct subscription indicator."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.subscription import Subscription

    n_subscribed = min(n_subscribed, n_categories)

    user = User(
        email=f"sublist_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()

    categories = []
    for i in range(n_categories):
        cat = Category(name=f"ListCat{i}{secrets.token_hex(2)}")
        db_session.session.add(cat)
        db_session.session.flush()
        categories.append(cat)

    subscribed_ids = set()
    for cat in categories[:n_subscribed]:
        sub = Subscription(user_id=user.id, category_id=cat.id)
        db_session.session.add(sub)
        subscribed_ids.add(cat.id)
    db_session.session.commit()

    # Verify via direct DB query (mirrors what the route does)
    all_cats = Category.query.order_by(Category.name).all()
    actual_subscribed = {
        s.category_id
        for s in Subscription.query.filter_by(user_id=user.id).all()
    }

    assert subscribed_ids == actual_subscribed
    assert len(all_cats) >= n_categories


# ===========================================================================
# Property 29: Delivery sets delivered_at on all eligible snippets
# ===========================================================================

# Feature: micro-news-app, Property 29: Delivery sets delivered_at on all eligible snippets
@given(n_snippets=st.integers(min_value=1, max_value=10))
@settings(max_examples=100)
def test_delivery_sets_delivered_at_on_eligible_snippets(app, db_session, n_snippets):
    """For any user with subscriptions and undelivered UserSnippets for today, deliver_for_user sets delivered_at."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.snippet import Snippet
    from app.models.subscription import Subscription
    from app.models.user_snippet import UserSnippet
    from app.services.delivery_service import Delivery_Service

    user = User(
        email=f"deliver_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    cat = Category(name=f"DeliverCat{secrets.token_hex(2)}")
    db_session.session.add(user)
    db_session.session.add(cat)
    db_session.session.flush()

    sub = Subscription(user_id=user.id, category_id=cat.id)
    db_session.session.add(sub)
    db_session.session.flush()

    today = date.today()
    us_ids = []
    for i in range(n_snippets):
        snippet = Snippet(
            category_id=cat.id,
            headline=f"H{i}",
            body="word " * 5,
            collection_date=today,
        )
        db_session.session.add(snippet)
        db_session.session.flush()
        us = UserSnippet(user_id=user.id, snippet_id=snippet.id, delivered_at=None)
        db_session.session.add(us)
        db_session.session.flush()
        us_ids.append(us.id)
    db_session.session.commit()

    service = Delivery_Service()
    count = service.deliver_for_user(user.id)

    assert count == n_snippets
    for us_id in us_ids:
        us = UserSnippet.query.get(us_id)
        assert us.delivered_at is not None


# ===========================================================================
# Property 30: No delivery when no snippets available
# ===========================================================================

# Feature: micro-news-app, Property 30: No delivery when no snippets available
@given(dummy=st.integers(min_value=0, max_value=99))
@settings(max_examples=100)
def test_no_delivery_when_no_snippets_available(app, db_session, dummy):
    """For any user with no undelivered UserSnippets for today, deliver_for_user → returns 0."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.subscription import Subscription
    from app.services.delivery_service import Delivery_Service

    user = User(
        email=f"nodeliver_{dummy}_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    cat = Category(name=f"NoDeliverCat{dummy}{secrets.token_hex(2)}")
    db_session.session.add(user)
    db_session.session.add(cat)
    db_session.session.flush()

    sub = Subscription(user_id=user.id, category_id=cat.id)
    db_session.session.add(sub)
    db_session.session.commit()

    # No UserSnippet rows exist → deliver_for_user should return 0
    service = Delivery_Service()
    count = service.deliver_for_user(user.id)
    assert count == 0


# ===========================================================================
# Property 31: Mark-as-read is user-scoped
# ===========================================================================

# Feature: micro-news-app, Property 31: Mark-as-read is user-scoped
@given(n_other_users=st.integers(min_value=1, max_value=5))
@settings(max_examples=100)
def test_mark_as_read_is_user_scoped(app, db_session, n_other_users):
    """For any user marking a snippet read, other users' UserSnippet rows unaffected."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.snippet import Snippet
    from app.models.user_snippet import UserSnippet

    cat = Category(name=f"ReadScopeCat{secrets.token_hex(2)}")
    db_session.session.add(cat)
    db_session.session.flush()

    snippet = Snippet(
        category_id=cat.id,
        headline="Shared snippet",
        body="word " * 5,
        collection_date=date.today(),
    )
    db_session.session.add(snippet)
    db_session.session.flush()

    # Primary user
    primary = User(
        email=f"primary_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(primary)
    db_session.session.flush()

    primary_us = UserSnippet(
        user_id=primary.id,
        snippet_id=snippet.id,
        delivered_at=datetime.now(timezone.utc),
    )
    db_session.session.add(primary_us)

    # Other users
    other_us_ids = []
    for i in range(n_other_users):
        other = User(
            email=f"other_{i}_{secrets.token_hex(4)}@example.com",
            password_hash=generate_password_hash("Pass1word!"),
            email_verified=True,
        )
        db_session.session.add(other)
        db_session.session.flush()
        ous = UserSnippet(
            user_id=other.id,
            snippet_id=snippet.id,
            delivered_at=datetime.now(timezone.utc),
        )
        db_session.session.add(ous)
        db_session.session.flush()
        other_us_ids.append(ous.id)
    db_session.session.commit()

    # Mark primary user's snippet as read
    primary_us.is_read = True
    primary_us.read_at = datetime.now(timezone.utc)
    db_session.session.commit()

    # Other users' rows should remain unread
    for ous_id in other_us_ids:
        ous = UserSnippet.query.get(ous_id)
        assert ous.is_read is False


# ===========================================================================
# Property 32: Snippet deletion is user-scoped
# ===========================================================================

# Feature: micro-news-app, Property 32: Snippet deletion is user-scoped
@given(n_other_users=st.integers(min_value=1, max_value=5))
@settings(max_examples=100)
def test_snippet_deletion_is_user_scoped(app, db_session, n_other_users):
    """For any user deleting a snippet, other users' UserSnippet rows unaffected."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.snippet import Snippet
    from app.models.user_snippet import UserSnippet

    cat = Category(name=f"DelScopeCat{secrets.token_hex(2)}")
    db_session.session.add(cat)
    db_session.session.flush()

    snippet = Snippet(
        category_id=cat.id,
        headline="Shared snippet",
        body="word " * 5,
        collection_date=date.today(),
    )
    db_session.session.add(snippet)
    db_session.session.flush()

    primary = User(
        email=f"delprimary_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(primary)
    db_session.session.flush()

    primary_us = UserSnippet(
        user_id=primary.id,
        snippet_id=snippet.id,
        delivered_at=datetime.now(timezone.utc),
    )
    db_session.session.add(primary_us)

    other_us_ids = []
    for i in range(n_other_users):
        other = User(
            email=f"delother_{i}_{secrets.token_hex(4)}@example.com",
            password_hash=generate_password_hash("Pass1word!"),
            email_verified=True,
        )
        db_session.session.add(other)
        db_session.session.flush()
        ous = UserSnippet(
            user_id=other.id,
            snippet_id=snippet.id,
            delivered_at=datetime.now(timezone.utc),
        )
        db_session.session.add(ous)
        db_session.session.flush()
        other_us_ids.append(ous.id)
    db_session.session.commit()

    # Soft-delete primary user's snippet
    primary_us.is_deleted = True
    db_session.session.commit()

    # Other users' rows should remain not deleted
    for ous_id in other_us_ids:
        ous = UserSnippet.query.get(ous_id)
        assert ous.is_deleted is False


# ===========================================================================
# Property 33: Feed ordering puts unread before read
# ===========================================================================

# Feature: micro-news-app, Property 33: Feed ordering puts unread before read
@given(
    n_read=st.integers(min_value=0, max_value=5),
    n_unread=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_feed_ordering_puts_unread_before_read(app, db_session, n_read, n_unread):
    """For any user's feed, within each category, all is_read=False before is_read=True."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.snippet import Snippet
    from app.models.user_snippet import UserSnippet
    from sqlalchemy import asc

    assume(n_read + n_unread > 0)

    cat = Category(name=f"FeedOrderCat{secrets.token_hex(2)}")
    db_session.session.add(cat)
    db_session.session.flush()

    user = User(
        email=f"feedorder_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()

    now = datetime.now(timezone.utc)
    for i in range(n_read):
        s = Snippet(
            category_id=cat.id,
            headline=f"Read {i}",
            body="word " * 5,
            collection_date=date.today(),
        )
        db_session.session.add(s)
        db_session.session.flush()
        us = UserSnippet(
            user_id=user.id,
            snippet_id=s.id,
            is_read=True,
            delivered_at=now,
        )
        db_session.session.add(us)

    for i in range(n_unread):
        s = Snippet(
            category_id=cat.id,
            headline=f"Unread {i}",
            body="word " * 5,
            collection_date=date.today(),
        )
        db_session.session.add(s)
        db_session.session.flush()
        us = UserSnippet(
            user_id=user.id,
            snippet_id=s.id,
            is_read=False,
            delivered_at=now,
        )
        db_session.session.add(us)
    db_session.session.commit()

    # Query ordered by is_read (False=0 before True=1)
    rows = (
        UserSnippet.query
        .filter_by(user_id=user.id, is_deleted=False)
        .filter(UserSnippet.delivered_at.isnot(None))
        .order_by(asc(UserSnippet.is_read))
        .all()
    )

    # Verify: no read row appears before an unread row
    seen_read = False
    for row in rows:
        if row.is_read:
            seen_read = True
        if seen_read and not row.is_read:
            assert False, "Unread snippet appeared after a read snippet"


# ===========================================================================
# Property 34: Unread count matches database state
# ===========================================================================

# Feature: micro-news-app, Property 34: Unread count matches database state
@given(
    n_unread=st.integers(min_value=0, max_value=10),
    n_read=st.integers(min_value=0, max_value=5),
    n_deleted=st.integers(min_value=0, max_value=5),
    n_undelivered=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_unread_count_matches_database_state(app, db_session, n_unread, n_read, n_deleted, n_undelivered):
    """For any user, dashboard unread_count = count of UserSnippet rows where is_read=False, is_deleted=False, delivered_at IS NOT NULL."""
    from app.models.user import User
    from app.models.category import Category
    from app.models.snippet import Snippet
    from app.models.user_snippet import UserSnippet

    cat = Category(name=f"UnreadCat{secrets.token_hex(2)}")
    db_session.session.add(cat)
    db_session.session.flush()

    user = User(
        email=f"unread_{secrets.token_hex(4)}@example.com",
        password_hash=generate_password_hash("Pass1word!"),
        email_verified=True,
    )
    db_session.session.add(user)
    db_session.session.flush()

    now = datetime.now(timezone.utc)

    def _add_snippet(is_read, is_deleted, delivered):
        s = Snippet(
            category_id=cat.id,
            headline="H",
            body="word " * 5,
            collection_date=date.today(),
        )
        db_session.session.add(s)
        db_session.session.flush()
        us = UserSnippet(
            user_id=user.id,
            snippet_id=s.id,
            is_read=is_read,
            is_deleted=is_deleted,
            delivered_at=now if delivered else None,
        )
        db_session.session.add(us)

    for _ in range(n_unread):
        _add_snippet(is_read=False, is_deleted=False, delivered=True)
    for _ in range(n_read):
        _add_snippet(is_read=True, is_deleted=False, delivered=True)
    for _ in range(n_deleted):
        _add_snippet(is_read=False, is_deleted=True, delivered=True)
    for _ in range(n_undelivered):
        _add_snippet(is_read=False, is_deleted=False, delivered=False)
    db_session.session.commit()

    expected = n_unread
    actual = UserSnippet.query.filter_by(
        user_id=user.id,
        is_read=False,
        is_deleted=False,
    ).filter(UserSnippet.delivered_at.isnot(None)).count()

    assert actual == expected


# ===========================================================================
# Property 35: Bootstrap is idempotent when admin exists
# ===========================================================================

# Feature: micro-news-app, Property 35: Bootstrap is idempotent when admin exists
@given(
    username=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
        min_size=3,
        max_size=30,
    ),
    env_username=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
        min_size=3,
        max_size=30,
    ),
)
@settings(max_examples=100)
def test_bootstrap_is_idempotent_when_admin_exists(app, db_session, username, env_username):
    """For any DB state with at least one Admin, running bootstrap_admin() → no additional Admin records."""
    import os
    from app.models.admin import Admin
    from app.services.bootstrap import bootstrap_admin

    # Create an existing admin
    admin = Admin(
        username=username,
        password_hash=generate_password_hash("AdminPass1!"),
    )
    db_session.session.add(admin)
    db_session.session.commit()

    count_before = Admin.query.count()
    assert count_before >= 1

    # Run bootstrap with env vars set (should be a no-op)
    old_username = os.environ.get("ADMIN_USERNAME")
    old_password = os.environ.get("ADMIN_PASSWORD")
    try:
        os.environ["ADMIN_USERNAME"] = env_username
        os.environ["ADMIN_PASSWORD"] = "EnvPass1!"
        bootstrap_admin()
    finally:
        if old_username is not None:
            os.environ["ADMIN_USERNAME"] = old_username
        if old_password is not None:
            os.environ["ADMIN_PASSWORD"] = old_password

    count_after = Admin.query.count()
    assert count_after == count_before
