"""Filter articles to the last 12 hours by publication time."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from src.models import RawArticle

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filter_last_n_days(articles: list[RawArticle], days: int, now: datetime | None = None) -> list[RawArticle]:
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _to_utc(now)

    cutoff = now - timedelta(days=days)
    kept: list[RawArticle] = []

    for article in articles:
        pub = _to_utc(article.published_at)
        if cutoff <= pub <= now:
            kept.append(article)

    logger.info(
        "Time filter: %d -> %d (%dd window ending %s UTC)",
        len(articles),
        len(kept),
        days,
        now.strftime("%Y-%m-%d %H:%M"),
    )
    return kept


def filter_last_12_hours(articles: list[RawArticle], now: datetime | None = None) -> list[RawArticle]:
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _to_utc(now)

    cutoff = now - timedelta(hours=12)
    kept: list[RawArticle] = []

    for article in articles:
        pub = _to_utc(article.published_at)
        if cutoff <= pub <= now:
            kept.append(article)

    logger.info(
        "Time filter: %d -> %d (12h window ending %s UTC)",
        len(articles),
        len(kept),
        now.strftime("%Y-%m-%d %H:%M"),
    )
    return kept
