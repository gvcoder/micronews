import functools
from datetime import datetime, timezone, timedelta, date, time
from itertools import groupby
from operator import attrgetter

from flask import flash, redirect, url_for, request, render_template, session
from flask_login import login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from app.user import user_app

# User session timeout: 120 minutes of inactivity
USER_SESSION_TIMEOUT = timedelta(minutes=120)


# ---------------------------------------------------------------------------
# Session timeout enforcement (task 6.5)
# ---------------------------------------------------------------------------

@user_app.before_request
def enforce_session_timeout():
    """Invalidate user session after 120 minutes of inactivity."""
    if current_user.is_authenticated:
        last_active = session.get('user_last_active')
        if last_active:
            last_active_dt = datetime.fromisoformat(last_active)
            if datetime.now(timezone.utc) - last_active_dt > USER_SESSION_TIMEOUT:
                logout_user()
                session.clear()
                flash('Your session has expired. Please log in again.', 'warning')
                return redirect(url_for('user_app.login'))
        session['user_last_active'] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# @login_required decorator (task 6.4)
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator that protects user routes; redirects to /login if not authenticated."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('user_app.login'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Registration (task 6.1)
# ---------------------------------------------------------------------------

@user_app.route('/register', methods=['GET', 'POST'])
def register():
    from app.models.user import User
    from app.services.email_validator import Email_Validator
    from app.services.password_validator import validate_password
    from app.services.password_reset_service import Password_Reset_Service

    if current_user.is_authenticated:
        return redirect(url_for('user_app.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        validator = Email_Validator()

        # Validate email format
        if not validator.validate_format(email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('user/register.html'), 422

        # Check for duplicate email
        if User.query.filter_by(email=email).first():
            flash('An account with that email address already exists.', 'danger')
            return render_template('user/register.html'), 422

        # Validate password policy
        valid, error_msg = validate_password(password)
        if not valid:
            flash(error_msg, 'danger')
            return render_template('user/register.html'), 422

        # Check password confirmation
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('user/register.html'), 422

        # Create user with email_verified=False
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            email_verified=False,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()

        # Send verification email
        try:
            service = Password_Reset_Service()
            service.send_verification_link(user)
        except Exception:
            pass  # Don't block registration if email fails

        flash(
            'Registration successful! Please check your email to verify your account.',
            'success',
        )
        return redirect(url_for('user_app.login'))

    return render_template('user/register.html')


# ---------------------------------------------------------------------------
# Login (task 6.2)
# ---------------------------------------------------------------------------

@user_app.route('/login', methods=['GET', 'POST'])
def login():
    from app.models.user import User

    if current_user.is_authenticated:
        return redirect(url_for('user_app.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()

        # Generic error — no field-specific hints
        if (
            user is None
            or not check_password_hash(user.password_hash, password)
            or not user.email_verified
            or not user.is_active
        ):
            flash('Invalid email or password.', 'danger')
            return render_template('user/login.html'), 401

        login_user(user)
        session.permanent = True
        session['user_last_active'] = datetime.now(timezone.utc).isoformat()

        next_page = request.args.get('next')
        return redirect(next_page or url_for('user_app.dashboard'))

    return render_template('user/login.html')


# ---------------------------------------------------------------------------
# Logout (task 6.3)
# ---------------------------------------------------------------------------

@user_app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('user_app.login'))


# ---------------------------------------------------------------------------
# Dashboard (task 11.1, 11.5)
# ---------------------------------------------------------------------------

@user_app.route('/dashboard')
@login_required
def dashboard():
    from app.models.user_snippet import UserSnippet
    from app.models.subscription import Subscription

    today = date.today()
    today_start = datetime.combine(today, time.min).replace(tzinfo=timezone.utc)
    today_end = datetime.combine(today, time.max).replace(tzinfo=timezone.utc)

    # Unread count: delivered, not deleted, not read
    unread_count = UserSnippet.query.filter_by(
        user_id=current_user.id,
        is_read=False,
        is_deleted=False,
    ).filter(UserSnippet.delivered_at.isnot(None)).count()

    # Today's delivered snippets count
    today_delivered_count = UserSnippet.query.filter_by(
        user_id=current_user.id,
        is_deleted=False,
    ).filter(
        UserSnippet.delivered_at.isnot(None),
        UserSnippet.delivered_at >= today_start,
        UserSnippet.delivered_at <= today_end,
    ).count()

    has_subscriptions = Subscription.query.filter_by(
        user_id=current_user.id
    ).first() is not None

    return render_template(
        'user/dashboard.html',
        unread_count=unread_count,
        today_delivered_count=today_delivered_count,
        has_subscriptions=has_subscriptions,
    )


# ---------------------------------------------------------------------------
# Feed (task 11.2, 11.5)
# ---------------------------------------------------------------------------

@user_app.route('/feed')
@login_required
def feed():
    from app.models.user_snippet import UserSnippet
    from app.models.snippet import Snippet
    from app.models.category import Category
    from app.models.subscription import Subscription

    # Fetch all delivered, non-deleted user snippets with their snippet/category
    user_snippets = (
        UserSnippet.query
        .join(Snippet, UserSnippet.snippet_id == Snippet.id)
        .join(Category, Snippet.category_id == Category.id)
        .filter(
            UserSnippet.user_id == current_user.id,
            UserSnippet.is_deleted == False,
            UserSnippet.delivered_at.isnot(None),
        )
        .order_by(Category.name, UserSnippet.is_read)
        .all()
    )

    # Group by category name, unread (is_read=False=0) before read (is_read=True=1)
    feed_by_category = []
    for cat_name, group in groupby(user_snippets, key=lambda us: us.snippet.category.name):
        feed_by_category.append((cat_name, list(group)))

    unread_count = sum(
        1 for us in user_snippets if not us.is_read
    )

    has_subscriptions = Subscription.query.filter_by(
        user_id=current_user.id
    ).first() is not None

    return render_template(
        'user/feed.html',
        feed_by_category=feed_by_category,
        has_subscriptions=has_subscriptions,
        unread_count=unread_count,
    )


# ---------------------------------------------------------------------------
# Mark as read (task 11.3)
# ---------------------------------------------------------------------------

@user_app.route('/feed/snippets/<int:snippet_id>/read', methods=['POST'])
@login_required
def mark_read(snippet_id):
    from app.models.user_snippet import UserSnippet

    us = UserSnippet.query.filter_by(
        id=snippet_id,
        user_id=current_user.id,
    ).first_or_404()

    us.is_read = True
    us.read_at = datetime.now(timezone.utc)
    db.session.commit()

    return redirect(url_for('user_app.feed'))


# ---------------------------------------------------------------------------
# Delete from feed (task 11.4)
# ---------------------------------------------------------------------------

@user_app.route('/feed/snippets/<int:snippet_id>/delete', methods=['POST'])
@login_required
def delete_snippet(snippet_id):
    from app.models.user_snippet import UserSnippet

    us = UserSnippet.query.filter_by(
        id=snippet_id,
        user_id=current_user.id,
    ).first_or_404()

    us.is_deleted = True
    db.session.commit()

    return redirect(url_for('user_app.feed'))


# ---------------------------------------------------------------------------
# Email verification (task 5.8)
# ---------------------------------------------------------------------------

@user_app.route('/verify/<token>')
def verify_email(token):
    """Consume an email verification token and activate the user account."""
    from app.services.password_reset_service import Password_Reset_Service

    service = Password_Reset_Service()
    success = service.consume_verification_token(token)

    if success:
        flash('Your email has been verified. You can now log in.', 'success')
    else:
        flash(
            'This verification link is invalid or has expired. '
            'Please request a new verification email.',
            'danger',
        )
    return redirect(url_for('user_app.login'))


# ---------------------------------------------------------------------------
# Profile view/update (tasks 7.1, 7.2, 7.3)
# ---------------------------------------------------------------------------

@user_app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    from app.models.user import User

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        birthday_str = request.form.get('birthday', '').strip()
        delivery_time_str = request.form.get('preferred_delivery_time', '').strip()

        # --- birthday validation (task 7.2) ---
        birthday = None
        if birthday_str:
            try:
                birthday = datetime.strptime(birthday_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Birthday must be a valid calendar date (YYYY-MM-DD).', 'danger')
                return render_template('user/profile.html', user=current_user), 422
            if birthday >= date.today():
                flash('Birthday must be a date in the past.', 'danger')
                return render_template('user/profile.html', user=current_user), 422

        # --- preferred_delivery_time parsing ---
        delivery_time = None
        if delivery_time_str:
            try:
                delivery_time = datetime.strptime(delivery_time_str, '%H:%M').time()
            except ValueError:
                flash('Preferred delivery time must be in HH:MM format.', 'danger')
                return render_template('user/profile.html', user=current_user), 422

        # Persist changes
        user = User.query.get(current_user.id)
        if name:
            user.name = name
        if birthday is not None:
            user.birthday = birthday
        delivery_time_changed = delivery_time is not None and delivery_time != user.preferred_delivery_time
        if delivery_time is not None:
            user.preferred_delivery_time = delivery_time
        db.session.commit()

        # Reschedule APScheduler delivery job if time changed (task 7.3)
        if delivery_time_changed:
            try:
                from app.services.delivery_service import schedule_delivery_job
                schedule_delivery_job(user)
            except Exception:
                pass  # Don't block profile save if scheduling fails

        flash('Profile updated successfully.', 'success')
        return redirect(url_for('user_app.profile'))

    return render_template('user/profile.html', user=current_user)


# ---------------------------------------------------------------------------
# Change password (task 7.4)
# ---------------------------------------------------------------------------

@user_app.route('/profile/change-password', methods=['POST'])
@login_required
def change_password():
    from app.services.password_reset_service import Password_Reset_Service

    try:
        service = Password_Reset_Service()
        service.send_reset_link(current_user)
        flash(
            'A password-reset link has been sent to your email address.',
            'success',
        )
    except Exception:
        flash('Could not send reset email. Please try again later.', 'danger')

    return redirect(url_for('user_app.profile'))


# ---------------------------------------------------------------------------
# Subscription management (tasks 8.1 – 8.4)
# ---------------------------------------------------------------------------

@user_app.route('/subscriptions')
@login_required
def subscriptions():
    from app.models.category import Category
    from app.models.subscription import Subscription

    categories = Category.query.order_by(Category.name).all()
    subscribed_ids = {
        s.category_id
        for s in Subscription.query.filter_by(user_id=current_user.id).all()
    }
    has_subscriptions = len(subscribed_ids) > 0
    return render_template(
        'user/subscriptions.html',
        categories=categories,
        subscribed_ids=subscribed_ids,
        has_subscriptions=has_subscriptions,
    )


@user_app.route('/subscriptions/<int:category_id>/subscribe', methods=['POST'])
@login_required
def subscribe(category_id):
    from app.models.subscription import Subscription
    from sqlalchemy.exc import IntegrityError

    existing = Subscription.query.filter_by(
        user_id=current_user.id, category_id=category_id
    ).first()
    if not existing:
        sub = Subscription(user_id=current_user.id, category_id=category_id)
        db.session.add(sub)
        try:
            db.session.commit()
            flash('Subscribed successfully.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('You are already subscribed to this category.', 'info')
    else:
        flash('You are already subscribed to this category.', 'info')
    return redirect(url_for('user_app.subscriptions'))


@user_app.route('/subscriptions/<int:category_id>/unsubscribe', methods=['POST'])
@login_required
def unsubscribe(category_id):
    from app.models.subscription import Subscription

    sub = Subscription.query.filter_by(
        user_id=current_user.id, category_id=category_id
    ).first()
    if sub:
        db.session.delete(sub)
        db.session.commit()
        flash('Unsubscribed successfully.', 'success')
    else:
        flash('You are not subscribed to this category.', 'info')
    return redirect(url_for('user_app.subscriptions'))


# ---------------------------------------------------------------------------
# Password reset form (task 7.5)
# ---------------------------------------------------------------------------

@user_app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from app.services.password_reset_service import Password_Reset_Service
    from app.services.password_validator import validate_password

    service = Password_Reset_Service()

    # Validate token upfront for both GET and POST
    user = service.validate_token(token)
    if user is None:
        flash(
            'This password-reset link is invalid or has expired. '
            'Please request a new one.',
            'danger',
        )
        return redirect(url_for('user_app.login')), 400

    if request.method == 'POST':
        new_password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        valid, error_msg = validate_password(new_password)
        if not valid:
            flash(error_msg, 'danger')
            return render_template('user/reset_password.html', token=token), 422

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('user/reset_password.html', token=token), 422

        success = service.consume_token(token, new_password)
        if success:
            flash('Your password has been reset. You can now log in.', 'success')
            return redirect(url_for('user_app.login'))
        else:
            flash('Password reset failed. The link may have already been used.', 'danger')
            return redirect(url_for('user_app.login')), 400

    return render_template('user/reset_password.html', token=token)
