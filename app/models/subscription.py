from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint
from app import db


class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    __table_args__ = (
        UniqueConstraint('user_id', 'category_id', name='uq_subscription_user_category'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    subscribed_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Subscription user={self.user_id} category={self.category_id}>'
