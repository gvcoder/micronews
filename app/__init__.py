import os
from datetime import timedelta

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
login_manager_admin = LoginManager()
login_manager_user = LoginManager()
scheduler = BackgroundScheduler()


def create_app(config_name=None):
    app = Flask(__name__)

    # Load config
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    from config import config
    app.config.from_object(config[config_name])

    # Task 3.4 – permanent session lifetime (used as the upper bound; inactivity
    # is enforced separately via the before_request hook in admin routes).
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=60)

    # Initialize extensions
    db.init_app(app)

    # Configure Flask-Login for admin
    login_manager_admin.session_protection = 'strong'
    login_manager_admin.login_view = 'admin_app.login'
    login_manager_admin.login_message_category = 'warning'
    login_manager_admin.init_app(app)

    # Configure Flask-Login for user (separate instance via request_loader)
    login_manager_user.session_protection = 'basic'
    login_manager_user.login_view = 'user_app.login'
    login_manager_user.login_message_category = 'warning'

    # Register blueprints
    from app.admin import admin_app
    app.register_blueprint(admin_app, url_prefix='/admin')

    from app.user import user_app
    app.register_blueprint(user_app, url_prefix='/')

    # Flask-Login user loaders
    @login_manager_admin.user_loader
    def load_admin(user_id):
        from app.models.admin import Admin
        return Admin.query.get(int(user_id))

    login_manager_user.init_app(app)

    @login_manager_user.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.query.get(int(user_id))

    # Initialize and start APScheduler
    if not scheduler.running:
        scheduler.start()
    app.scheduler = scheduler

    # Task 3.6 – bootstrap admin account on startup
    with app.app_context():
        from app.services.bootstrap import bootstrap_admin
        bootstrap_admin()

    # Task 9.5 – schedule daily news collection at 09:00 IST (03:30 UTC)
    from apscheduler.triggers.cron import CronTrigger
    from app.services.collection_service import run_news_collection

    def _run_collection_with_context():
        with app.app_context():
            run_news_collection()

    scheduler.add_job(
        _run_collection_with_context,
        trigger=CronTrigger(hour=3, minute=30, timezone='UTC'),
        id='news_collection',
        replace_existing=True,
    )

    # Task 10.4 – reschedule delivery jobs for all users with a preferred_delivery_time
    with app.app_context():
        from app.models.user import User
        from app.services.delivery_service import schedule_delivery_job
        users_with_delivery_time = User.query.filter(
            User.preferred_delivery_time.isnot(None)
        ).all()
        for _user in users_with_delivery_time:
            try:
                schedule_delivery_job(_user)
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).exception(
                    'Failed to reschedule delivery job for user %s', _user.id
                )

    return app
