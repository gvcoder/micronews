import functools
from datetime import datetime, timezone, timedelta, date

from flask import (
    render_template, redirect, url_for, request, flash, session, abort
)
from flask_login import login_user, logout_user, current_user
from sqlalchemy import func
from werkzeug.security import check_password_hash

from app import db
from app.admin import admin_app
from app.admin.rate_limiter import is_blocked, record_failure, record_success

# Admin session timeout: 60 minutes of inactivity
ADMIN_SESSION_TIMEOUT = timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Session timeout enforcement
# ---------------------------------------------------------------------------

@admin_app.before_request
def enforce_session_timeout():
    """Invalidate admin session after 60 minutes of inactivity."""
    if current_user.is_authenticated:
        last_active = session.get('admin_last_active')
        if last_active:
            last_active_dt = datetime.fromisoformat(last_active)
            if datetime.now(timezone.utc) - last_active_dt > ADMIN_SESSION_TIMEOUT:
                logout_user()
                session.clear()
                flash('Your session has expired. Please log in again.', 'warning')
                return redirect(url_for('admin_app.login'))
        session['admin_last_active'] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# @admin_required decorator (task 3.3)
# ---------------------------------------------------------------------------

def admin_required(f):
    """Decorator that protects admin routes; redirects to login if not authenticated."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('admin_app.login'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Login / Logout routes (tasks 3.1, 3.2)
# ---------------------------------------------------------------------------

@admin_app.route('/login', methods=['GET', 'POST'])
def login():
    from app.models.admin import Admin

    if current_user.is_authenticated:
        return redirect(url_for('admin_app.dashboard'))

    if request.method == 'POST':
        ip = request.remote_addr

        # Task 3.5 – rate limit check
        if is_blocked(ip):
            return (
                render_template('admin/login.html',
                                error='Too many attempts, try again in 15 minutes.'),
                429,
            )

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        admin = Admin.query.filter_by(username=username).first()

        if admin and check_password_hash(admin.password_hash, password):
            record_success(ip)
            login_user(admin)
            session.permanent = True
            session['admin_last_active'] = datetime.now(timezone.utc).isoformat()
            return redirect(url_for('admin_app.dashboard'))

        # Invalid credentials
        blocked_now = record_failure(ip)
        if blocked_now:
            return (
                render_template('admin/login.html',
                                error='Too many attempts, try again in 15 minutes.'),
                429,
            )

        return (
            render_template('admin/login.html',
                            error='Invalid username or password.'),
            401,
        )

    return render_template('admin/login.html')


@admin_app.route('/logout', methods=['POST'])
@admin_required
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_app.login'))


# ---------------------------------------------------------------------------
# Dashboard (task 4.1)
# ---------------------------------------------------------------------------

@admin_app.route('/dashboard')
@admin_required
def dashboard():
    from app.models.category import Category
    from app.models.collection_log import CollectionLog

    category_count = Category.query.count()

    today = date.today()
    today_log = (
        CollectionLog.query
        .filter(func.date(CollectionLog.run_at) == today)
        .order_by(CollectionLog.run_at.desc())
        .first()
    )

    return render_template(
        'admin/dashboard.html',
        category_count=category_count,
        today_log=today_log,
    )


# ---------------------------------------------------------------------------
# Category list (task 4.2)
# ---------------------------------------------------------------------------

@admin_app.route('/categories')
@admin_required
def category_list():
    from app.models.category import Category

    page = request.args.get('page', 1, type=int)
    pagination = (
        Category.query
        .order_by(func.lower(Category.name))
        .paginate(page=page, per_page=20, error_out=False)
    )

    return render_template(
        'admin/category_list.html',
        pagination=pagination,
        categories=pagination.items,
    )


# ---------------------------------------------------------------------------
# Category creation (task 4.3)
# ---------------------------------------------------------------------------

@admin_app.route('/categories/new', methods=['POST'])
@admin_required
def category_create():
    from app.models.category import Category

    name = request.form.get('name', '').strip()
    if not name:
        flash('Category name cannot be empty.', 'danger')
        return redirect(url_for('admin_app.category_list'))

    existing = Category.query.filter(func.lower(Category.name) == name.lower()).first()
    if existing:
        flash(f'A category named "{existing.name}" already exists.', 'danger')
        return redirect(url_for('admin_app.category_list'))

    category = Category(name=name)
    db.session.add(category)
    db.session.commit()
    flash(f'Category "{name}" created successfully.', 'success')
    return redirect(url_for('admin_app.category_list'))


# ---------------------------------------------------------------------------
# Category deletion – confirmation (task 4.4) and execution (tasks 4.4, 4.5)
# ---------------------------------------------------------------------------

@admin_app.route('/categories/<int:category_id>/delete', methods=['GET'])
@admin_required
def category_delete_confirm(category_id):
    from app.models.category import Category
    from app.models.subscription import Subscription

    category = Category.query.get_or_404(category_id)
    affected_users = Subscription.query.filter_by(category_id=category_id).count()

    return render_template(
        'admin/category_delete_confirm.html',
        category=category,
        affected_users=affected_users,
    )


@admin_app.route('/categories/<int:category_id>/delete', methods=['POST'])
@admin_required
def category_delete(category_id):
    from app.models.category import Category
    from app.models.snippet import Snippet
    from app.models.user_snippet import UserSnippet
    from app.models.subscription import Subscription

    category = Category.query.get_or_404(category_id)

    # Cascade: delete UserSnippets for all snippets in this category
    snippet_ids = db.session.query(Snippet.id).filter_by(category_id=category_id).subquery()
    UserSnippet.query.filter(UserSnippet.snippet_id.in_(snippet_ids)).delete(synchronize_session='fetch')

    # Delete Snippets
    Snippet.query.filter_by(category_id=category_id).delete()

    # Delete Subscriptions
    Subscription.query.filter_by(category_id=category_id).delete()

    # Delete Category
    db.session.delete(category)
    db.session.commit()

    flash(f'Category "{category.name}" and all associated data have been deleted.', 'success')
    return redirect(url_for('admin_app.category_list'))


# ---------------------------------------------------------------------------
# Collection log (task 4.6)
# ---------------------------------------------------------------------------

@admin_app.route('/collection-log')
@admin_required
def collection_log():
    from app.models.collection_log import CollectionLog

    page = request.args.get('page', 1, type=int)
    pagination = (
        CollectionLog.query
        .order_by(CollectionLog.run_at.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )

    return render_template(
        'admin/collection_log.html',
        pagination=pagination,
        logs=pagination.items,
    )
