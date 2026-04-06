from datetime import datetime, timezone
from app import db


class Snippet(db.Model):
    __tablename__ = 'snippets'

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    headline = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    source_url = db.Column(db.String(2048), nullable=True)
    collection_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user_snippets = db.relationship('UserSnippet', backref='snippet', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Snippet {self.id}: {self.headline[:40]}>'
