"""Collect news from all configured sources."""

from __future__ import annotations

import logging
import time

from src.collectors.gdelt import fetch_gdelt
from src.collectors.google_news import fetch_google_news
from src.collectors.rss import fetch_all_rss
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


def _collect_google_and_gdelt(seen_urls: set[str], out: list[RawArticle]) -> int:
    keywords_cfg = load_yaml("keywords.yaml")
    languages_cfg = load_yaml("languages.yaml")["languages"]
    coll_cfg = _collection_settings()
    gdelt_threshold = coll_cfg.get("gdelt_min_google_news", 8)
    gdelt_delay = coll_cfg.get("gdelt_delay_sec", 3.0)
    gdelt_calls = 0
    google_total = 0

    for topic_entry in keywords_cfg["topics"]:
        topic_name = topic_entry["name"]
        for lang_code, lang_cfg in languages_cfg.items():
            keywords = topic_entry["keywords"].get(lang_code, [])
            combined = _combine_keywords(keywords)
            if not combined:
                continue

            google_batch = fetch_google_news(combined, lang_code, lang_cfg, topic_name, max_items=25)
            google_count = _append_unique(google_batch, seen_urls, out)
            google_total += google_count

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
                gdelt_added = _append_unique(gdelt_batch, seen_urls, out)
                gdelt_calls += 1
                logger.info("GDELT supplement [%s/%s]: +%d articles", topic_name, lang_code, gdelt_added)

    logger.info("Google/GDELT: %d articles (%d GDELT calls)", google_total, gdelt_calls)
    return gdelt_calls


def collect_all(include_rss: bool | None = None) -> list[RawArticle]:
    coll_cfg = _collection_settings()
    if include_rss is None:
        include_rss = coll_cfg.get("rss_enabled", True)

    all_articles: list[RawArticle] = []
    seen_urls: set[str] = set()

    if include_rss:
        rss_batch = fetch_all_rss()
        rss_added = _append_unique(rss_batch, seen_urls, all_articles)
        logger.info("RSS feeds: +%d unique articles", rss_added)

    gdelt_calls = _collect_google_and_gdelt(seen_urls, all_articles)

    logger.info(
        "Collected %d unique articles (RSS=%s, GDELT supplements: %d calls)",
        len(all_articles),
        include_rss,
        gdelt_calls,
    )
    return all_articles
