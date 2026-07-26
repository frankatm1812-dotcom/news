"""GDELT DOC 2.0 API collector."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from src.models import RawArticle

logger = logging.getLogger(__name__)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT = 45.0
MAX_RETRIES = 3


def _parse_gdelt_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    formats = (
        "%Y%m%dT%H%M%SZ",
        "%Y%m%dT%H%M%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in formats:
        try:
            sample = value[: len(fmt.replace("%", "0"))]
            dt = datetime.strptime(sample, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fetch_gdelt(
    keyword: str,
    lang_code: str,
    lang_cfg: dict,
    topic: str,
    max_items: int = 25,
) -> list[RawArticle]:
    gdelt_lang = lang_cfg.get("gdelt_lang", "")
    if " OR " in keyword:
        query_core = f"({keyword})"
    else:
        query_core = f'"{keyword}"' if " " in keyword else keyword
    query_parts = [query_core]
    if gdelt_lang:
        query_parts.append(f"sourcelang:{gdelt_lang}")
    query = " ".join(query_parts)

    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(max_items),
        "format": "json",
        "timespan": "12h",
        "sort": "datedesc",
    }
    url = GDELT_URL + "?" + "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())

    articles: list[RawArticle] = []
    data = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                logger.warning("GDELT rate limited, retry in %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            if attempt == MAX_RETRIES - 1:
                logger.warning("GDELT fetch failed [%s/%s]: %s", lang_code, keyword[:40], exc)
                return articles
            time.sleep((attempt + 1) * 3)

    if not data:
        return articles

    for item in data.get("articles", []):
        title = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        source = (item.get("domain") or item.get("sourcecountry") or "Unknown").strip()
        pub_date = _parse_gdelt_date(item.get("seendate"))

        if not title or not link or pub_date is None:
            continue

        articles.append(
            RawArticle(
                title=title,
                url=link,
                source=source,
                published_at=pub_date,
                language=lang_code,
                topic_hint=topic,
                summary="",
                collector="gdelt",
            )
        )

    return articles
