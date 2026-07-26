"""Select articles spread across a time window instead of only the most recent."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.config_loader import load_yaml
from src.models import RawArticle
from src.processors.source_authority import get_source_score

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _article_rank(art: RawArticle) -> tuple:
    return (get_source_score(art.source), _to_utc(art.published_at))


def cap_with_time_spread(
    articles: list[RawArticle],
    cap: int,
    window_hours: int = 12,
    now: datetime | None = None,
) -> list[RawArticle]:
    """Pick up to `cap` articles evenly across the last `window_hours` hours."""
    if len(articles) <= cap:
        return sorted(articles, key=lambda a: _to_utc(a.published_at), reverse=True)

    now = _to_utc(now or datetime.now(timezone.utc))
    num_buckets = min(window_hours, cap)

    buckets: list[list[RawArticle]] = [[] for _ in range(num_buckets)]
    for art in articles:
        hours_ago = (now - _to_utc(art.published_at)).total_seconds() / 3600
        if hours_ago < 0 or hours_ago > window_hours:
            continue
        idx = min(int(hours_ago), num_buckets - 1)
        buckets[idx].append(art)

    for bucket in buckets:
        bucket.sort(key=_article_rank, reverse=True)

    selected: list[RawArticle] = []
    # Oldest hour first so quiet early hours still get representation
    bucket_order = list(range(num_buckets - 1, -1, -1))

    while len(selected) < cap:
        added = False
        for idx in bucket_order:
            if buckets[idx]:
                selected.append(buckets[idx].pop(0))
                added = True
                if len(selected) >= cap:
                    break
        if not added:
            break

    selected.sort(key=lambda a: _to_utc(a.published_at), reverse=True)
    logger.info(
        "Time-spread cap: %d -> %d articles across %d hourly buckets",
        len(articles),
        len(selected),
        num_buckets,
    )
    return selected


def cap_articles(
    articles: list[RawArticle],
    cap: int,
    now: datetime | None = None,
) -> list[RawArticle]:
    cfg = load_yaml("settings.yaml").get("processing", {})
    strategy = cfg.get("cap_strategy", "time_spread")
    window_hours = cfg.get("cap_window_hours", 12)

    if strategy == "recent":
        result = sorted(articles, key=lambda a: _to_utc(a.published_at), reverse=True)[:cap]
        logger.info("Recent cap: %d -> %d articles", len(articles), len(result))
        return result

    return cap_with_time_spread(articles, cap, window_hours=window_hours, now=now)
