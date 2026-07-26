"""Google News RSS collector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx

from src.models import RawArticle

logger = logging.getLogger(__name__)

RSS_BASE = "https://news.google.com/rss/search"
TIMEOUT = 30.0


def _parse_pub_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _extract_source(item: ElementTree.Element) -> str:
    source_el = item.find("source")
    if source_el is not None and source_el.text:
        return source_el.text.strip()
    title = item.findtext("title") or ""
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return "Unknown"


def _clean_title(title: str, source: str) -> str:
    suffix = f" - {source}"
    if title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title.strip()


def fetch_google_news(
    keyword: str,
    lang_code: str,
    lang_cfg: dict,
    topic: str,
    max_items: int = 20,
) -> list[RawArticle]:
    params = {
        "q": keyword,
        "hl": lang_cfg["google_hl"],
        "gl": lang_cfg["google_gl"],
        "ceid": lang_cfg["google_ceid"],
    }
    query = "&".join(f"{k}={quote_plus(str(v))}" for k, v in params.items())
    url = f"{RSS_BASE}?{query}"

    articles: list[RawArticle] = []
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except Exception as exc:
        logger.warning("Google News fetch failed [%s/%s]: %s", lang_code, keyword, exc)
        return articles

    channel = root.find("channel")
    if channel is None:
        return articles

    for item in channel.findall("item")[:max_items]:
        title_raw = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = _parse_pub_date(item.findtext("pubDate"))
        summary = item.findtext("description") or ""

        if not title_raw or not link or pub_date is None:
            continue

        source = _extract_source(item)
        title = _clean_title(title_raw, source)

        articles.append(
            RawArticle(
                title=title,
                url=link,
                source=source,
                published_at=pub_date,
                language=lang_code,
                topic_hint=topic,
                summary=summary,
                collector="google_news",
            )
        )

    return articles
