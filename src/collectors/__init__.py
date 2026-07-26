"""Collect news from all configured sources."""

from __future__ import annotations

import logging
import time

from src.collectors.gdelt import fetch_gdelt
from src.collectors.google_news import fetch_google_news
from src.config_loader import load_yaml
from src.models import RawArticle

logger = logging.getLogger(__name__)


def _collection_settings() -> dict:
    cfg = load_yaml("settings.yaml")
    return cfg.get("collection", {})


def _combine_keywords(keywords: list[str]) -> str:
    parts = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        parts.append(f'"{kw}"' if " " in kw else kw)
    return " OR ".join(parts) if parts else ""


def _normalize_url(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def _append_unique(batch: list[RawArticle], seen_urls: set[str], out: list[RawArticle]) -> int:
    added = 0
    for article in batch:
        key = _normalize_url(article.url)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        out.append(article)
        added += 1
    return added


def collect_all() -> list[RawArticle]:
    keywords_cfg = load_yaml("keywords.yaml")
    languages_cfg = load_yaml("languages.yaml")["languages"]
    coll_cfg = _collection_settings()
    gdelt_threshold = coll_cfg.get("gdelt_min_google_news", 8)
    gdelt_delay = coll_cfg.get("gdelt_delay_sec", 3.0)

    all_articles: list[RawArticle] = []
    seen_urls: set[str] = set()
    gdelt_calls = 0

    for topic_entry in keywords_cfg["topics"]:
        topic_name = topic_entry["name"]
        for lang_code, lang_cfg in languages_cfg.items():
            keywords = topic_entry["keywords"].get(lang_code, [])
            combined = _combine_keywords(keywords)
            if not combined:
                continue

            google_batch = fetch_google_news(combined, lang_code, lang_cfg, topic_name, max_items=25)
            google_count = _append_unique(google_batch, seen_urls, all_articles)

            if google_count < gdelt_threshold:
                logger.info(
                    "Google News [%s/%s] returned %d (< %d), fetching GDELT supplement",
                    topic_name,
                    lang_code,
                    google_count,
                    gdelt_threshold,
                )
                time.sleep(gdelt_delay)
                gdelt_batch = fetch_gdelt(combined, lang_code, lang_cfg, topic_name, max_items=25)
                gdelt_added = _append_unique(gdelt_batch, seen_urls, all_articles)
                gdelt_calls += 1
                logger.info("GDELT supplement [%s/%s]: +%d articles", topic_name, lang_code, gdelt_added)
            else:
                logger.debug(
                    "Google News [%s/%s] sufficient (%d), skipping GDELT",
                    topic_name,
                    lang_code,
                    google_count,
                )

    logger.info(
        "Collected %d unique articles (GDELT supplements: %d calls)",
        len(all_articles),
        gdelt_calls,
    )
    return all_articles
