"""
Collection service: runs the news collection job for all categories.
"""
import json
import logging
import re
from datetime import date, datetime, timezone

from app import db
from app.models.category import Category
from app.models.collection_log import CollectionLog
from app.models.snippet import Snippet
from app.models.subscription import Subscription
from app.models.user_snippet import UserSnippet
from app.agents.news_agent import build_news_crew

logger = logging.getLogger(__name__)

MAX_SNIPPETS_PER_CATEGORY = 10


def _parse_crew_output(output: str, category_id: int) -> list[dict]:
    """
    Parse the crew's text output into a list of snippet dicts.
    Expected format per article (separated by ---):
        HEADLINE: <title>
        SUMMARY: <summary>
        URL: <url or N/A>
    Falls back to splitting by newlines if the structured format is not found.
    """
    snippets = []
    today = date.today()

    # Split on --- separator
    blocks = re.split(r'\n\s*---\s*\n|---', output)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        headline = None
        body = None
        source_url = None

        # Try structured extraction
        headline_match = re.search(r'HEADLINE:\s*(.+)', block, re.IGNORECASE)
        summary_match = re.search(r'SUMMARY:\s*(.+?)(?=URL:|$)', block, re.IGNORECASE | re.DOTALL)
        url_match = re.search(r'URL:\s*(\S+)', block, re.IGNORECASE)

        if headline_match:
            headline = headline_match.group(1).strip()
        if summary_match:
            body = summary_match.group(1).strip()
        if url_match:
            raw_url = url_match.group(1).strip()
            source_url = None if raw_url.upper() in ('N/A', 'NONE', '') else raw_url

        # Fallback: use first line as headline, rest as body
        if not headline:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if lines:
                headline = lines[0][:300]
                body = ' '.join(lines[1:]) if len(lines) > 1 else headline

        if not headline or not body:
            continue

        # Enforce 60-word limit on body
        words = body.split()
        if len(words) > 60:
            body = ' '.join(words[:60])

        snippets.append({
            'headline': headline[:300],
            'body': body,
            'source_url': source_url,
            'collection_date': today,
            'category_id': category_id,
        })

        if len(snippets) >= MAX_SNIPPETS_PER_CATEGORY:
            break

    return snippets


def run_news_collection() -> None:
    """
    Main collection job. Iterates over all categories, runs the CrewAI crew
    for each, parses output into Snippet records (max 10 per category),
    persists to DB, creates UserSnippet rows for subscribed users, and
    writes a CollectionLog entry at the end.
    """
    from app import db  # ensure we have the app-context-bound db

    logger.info('Starting news collection run')

    categories = Category.query.order_by(Category.name).all()

    total_snippets = 0
    categories_processed = 0
    categories_failed = 0
    failure_details: list[dict] = []

    for category in categories:
        try:
            logger.info('Collecting news for category: %s', category.name)
            crew = build_news_crew(category.name)
            result = crew.kickoff()

            # crew.kickoff() may return a CrewOutput object or a string
            output_text = str(result) if not isinstance(result, str) else result

            snippet_dicts = _parse_crew_output(output_text, category.id)

            new_snippets = []
            for s in snippet_dicts:
                snippet = Snippet(
                    category_id=s['category_id'],
                    headline=s['headline'],
                    body=s['body'],
                    source_url=s['source_url'],
                    collection_date=s['collection_date'],
                )
                db.session.add(snippet)
                new_snippets.append(snippet)

            db.session.flush()  # assign IDs before creating UserSnippets

            # Create UserSnippet rows for all users subscribed to this category
            subscriptions = Subscription.query.filter_by(category_id=category.id).all()
            for subscription in subscriptions:
                for snippet in new_snippets:
                    user_snippet = UserSnippet(
                        user_id=subscription.user_id,
                        snippet_id=snippet.id,
                        delivered_at=None,
                    )
                    db.session.add(user_snippet)

            db.session.commit()

            total_snippets += len(new_snippets)
            categories_processed += 1
            logger.info(
                'Collected %d snippets for category "%s"',
                len(new_snippets),
                category.name,
            )

        except Exception as exc:
            db.session.rollback()
            categories_failed += 1
            error_entry = {
                'category': category.name,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(exc),
            }
            failure_details.append(error_entry)
            logger.exception('Failed to collect news for category "%s": %s', category.name, exc)

    # Write CollectionLog
    log_entry = CollectionLog(
        run_at=datetime.now(timezone.utc),
        total_snippets=total_snippets,
        categories_processed=categories_processed,
        categories_failed=categories_failed,
        failure_details=json.dumps(failure_details) if failure_details else None,
    )
    db.session.add(log_entry)
    db.session.commit()

    logger.info(
        'News collection run complete: %d snippets, %d processed, %d failed',
        total_snippets,
        categories_processed,
        categories_failed,
    )
