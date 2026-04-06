from sqlalchemy import UniqueConstraint
from app import db


class UserSnippet(db.Model):
    __tablename__ = 'user_snippets'
    __table_args__ = (
        UniqueConstraint('user_id', 'snippet_id', name='uq_user_snippet'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    snippet_id = db.Column(db.Integer, db.ForeignKey('snippets.id'), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    delivered_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<UserSnippet user={self.user_id} snippet={self.snippet_id}>'
