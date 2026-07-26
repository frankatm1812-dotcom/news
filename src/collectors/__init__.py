"""Collect news from all configured sources."""

from __future__ import annotations

import logging
import time

from src.collectors.gdelt import fetch_gdelt
from src.collectors.google_news import fetch_google_news
from src.config_loader import load_yaml
from src.models import RawArticle

logger = logging.getLogger(__name__)

GDELT_DELAY_SEC = 3.0


def _combine_keywords(keywords: list[str]) -> str:
    """Build OR query for multi-keyword search."""
    parts = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        if " " in kw:
            parts.append(f'"{kw}"')
        else:
            parts.append(kw)
    return " OR ".join(parts) if parts else ""


def collect_all() -> list[RawArticle]:
    keywords_cfg = load_yaml("keywords.yaml")
    languages_cfg = load_yaml("languages.yaml")["languages"]

    all_articles: list[RawArticle] = []
    seen_urls: set[str] = set()

    for topic_entry in keywords_cfg["topics"]:
        topic_name = topic_entry["name"]
        for lang_code, lang_cfg in languages_cfg.items():
            keywords = topic_entry["keywords"].get(lang_code, [])
            combined = _combine_keywords(keywords)
            if not combined:
                continue

            # Google News: one query per topic+language
            batch = fetch_google_news(combined, lang_code, lang_cfg, topic_name, max_items=25)
            for article in batch:
                normalized_url = article.url.split("?")[0].rstrip("/")
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                all_articles.append(article)

            # GDELT: rate-limited, one query per topic+language
            time.sleep(GDELT_DELAY_SEC)
            batch = fetch_gdelt(combined, lang_code, lang_cfg, topic_name, max_items=25)
            for article in batch:
                normalized_url = article.url.split("?")[0].rstrip("/")
                if normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)
                all_articles.append(article)

    logger.info("Collected %d unique articles", len(all_articles))
    return all_articles
