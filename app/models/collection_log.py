from datetime import datetime, timezone
from app import db


class CollectionLog(db.Model):
    __tablename__ = 'collection_logs'

    id = db.Column(db.Integer, primary_key=True)
    run_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    total_snippets = db.Column(db.Integer, nullable=False, default=0)
    categories_processed = db.Column(db.Integer, nullable=False, default=0)
    categories_failed = db.Column(db.Integer, nullable=False, default=0)
    # JSON-serialized list of {category, error} objects
    failure_details = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<CollectionLog run_at={self.run_at} snippets={self.total_snippets}>'
