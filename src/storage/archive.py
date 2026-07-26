"""Persist and load daily briefing archives for weekly reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config_loader import project_root
from src.models import ProcessedArticle

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))
ARCHIVE_DIR = project_root() / "data" / "archive"


def _archive_path(date_str: str) -> Path:
    return ARCHIVE_DIR / f"{date_str}.json"


def _dt_to_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _dt_from_str(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def article_to_dict(art: ProcessedArticle) -> dict:
    return {
        "title_original": art.title_original,
        "title_zh": art.title_zh,
        "url": art.url,
        "source": art.source,
        "source_score": art.source_score,
        "published_at": _dt_to_str(art.published_at),
        "language": art.language,
        "topic": art.topic,
        "region": art.region,
        "facts_zh": art.facts_zh,
        "credibility": art.credibility,
        "credibility_label": art.credibility_label,
        "cluster_id": art.cluster_id,
        "cluster_sources": art.cluster_sources,
        "all_titles": art.all_titles,
    }


def article_from_dict(data: dict) -> ProcessedArticle:
    return ProcessedArticle(
        title_original=data["title_original"],
        title_zh=data["title_zh"],
        url=data["url"],
        source=data["source"],
        source_score=int(data.get("source_score", 40)),
        published_at=_dt_from_str(data["published_at"]),
        language=data["language"],
        topic=data["topic"],
        facts_zh=list(data.get("facts_zh", [])),
        credibility=data.get("credibility", "red"),
        credibility_label=data.get("credibility_label", "🔴 单一来源"),
        region=data.get("region", ""),
        cluster_id=data.get("cluster_id"),
        cluster_sources=list(data.get("cluster_sources", [])),
        all_titles=dict(data.get("all_titles", {})),
    )


def beijing_date_str(when: datetime | None = None) -> str:
    when = when or datetime.now(BEIJING_TZ)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(BEIJING_TZ).strftime("%Y-%m-%d")


def save_daily_archive(articles: list[ProcessedArticle], date_str: str | None = None) -> Path:
    date_str = date_str or beijing_date_str()
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = _archive_path(date_str)

    existing: list[ProcessedArticle] = []
    if path.exists():
        existing = load_archive(date_str)

    merged = _merge_archives(existing, articles)
    payload = {
        "date": date_str,
        "generated_at": _dt_to_str(datetime.now(timezone.utc)),
        "count": len(merged),
        "articles": [article_to_dict(a) for a in merged],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Archived %d articles to %s", len(merged), path)
    return path


def _merge_archives(existing: list[ProcessedArticle], new_items: list[ProcessedArticle]) -> list[ProcessedArticle]:
    by_url: dict[str, ProcessedArticle] = {}
    for art in existing + new_items:
        key = art.url.split("?")[0].rstrip("/")
        if key not in by_url or art.source_score > by_url[key].source_score:
            by_url[key] = art
    return sorted(by_url.values(), key=lambda a: a.published_at, reverse=True)


def load_archive(date_str: str) -> list[ProcessedArticle]:
    path = _archive_path(date_str)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [article_from_dict(item) for item in data.get("articles", [])]
    except Exception as exc:
        logger.warning("Failed to load archive %s: %s", date_str, exc)
        return []


def load_archives_last_n_days(days: int = 7, end_date: datetime | None = None) -> dict[str, list[ProcessedArticle]]:
    end = end_date or datetime.now(BEIJING_TZ)
    if end.tzinfo is None:
        end = end.replace(tzinfo=BEIJING_TZ)

    result: dict[str, list[ProcessedArticle]] = {}
    for offset in range(days):
        day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
        articles = load_archive(day)
        if articles:
            result[day] = articles
    return result


def flatten_archives(by_day: dict[str, list[ProcessedArticle]]) -> list[ProcessedArticle]:
    merged: dict[str, ProcessedArticle] = {}
    for day in sorted(by_day.keys()):
        for art in by_day[day]:
            key = art.url.split("?")[0].rstrip("/")
            if key not in merged:
                merged[key] = art
    return sorted(merged.values(), key=lambda a: a.published_at, reverse=True)
