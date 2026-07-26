"""Direct RSS feed collector for curated free sources."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from src.config_loader import load_yaml
from src.models import RawArticle

logger = logging.getLogger(__name__)

TIMEOUT = 20.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsBriefingBot/1.0; +https://github.com/frankatm1812-dotcom/news)"
)


def _parse_pub_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[: len(fmt.replace("%z", "+0000"))], fmt.replace("%z", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _find_text(parent: ElementTree.Element, name: str) -> str:
    el = _find_child(parent, name)
    return (el.text or "").strip() if el is not None else ""


def _extract_link(entry: ElementTree.Element) -> str:
    for child in entry:
        if _local(child.tag) == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
            if child.text:
                return child.text.strip()
    return _find_text(entry, "link")


def _parse_feed_xml(content: bytes, feed_cfg: dict) -> list[RawArticle]:
    articles: list[RawArticle] = []
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        logger.warning("RSS parse error [%s]: %s", feed_cfg.get("name"), exc)
        return articles

    root_name = _local(root.tag)
    entries: list[ElementTree.Element] = []

    if root_name == "rss":
        channel = _find_child(root, "channel")
        if channel is not None:
            entries = [el for el in channel if _local(el.tag) == "item"]
    elif root_name == "feed":
        entries = [el for el in root if _local(el.tag) == "entry"]
    else:
        return articles

    feed_name = feed_cfg.get("name", "RSS")
    topic = feed_cfg.get("topic", "其他")
    language = feed_cfg.get("language", "en")
    max_items = feed_cfg.get("max_items", 15)

    for entry in entries[:max_items]:
        title = _find_text(entry, "title")
        link = _extract_link(entry)
        summary = _find_text(entry, "description") or _find_text(entry, "summary")
        pub_date = _parse_pub_date(_find_text(entry, "pubDate") or _find_text(entry, "published") or _find_text(entry, "updated"))

        source_el = _find_child(entry, "source")
        source = (source_el.text or "").strip() if source_el is not None and source_el.text else feed_name

        if not title or not link or pub_date is None:
            continue

        articles.append(
            RawArticle(
                title=title,
                url=link,
                source=source,
                published_at=pub_date,
                language=language,
                topic_hint=topic,
                summary=summary,
                collector=f"rss:{feed_name}",
            )
        )

    return articles


def fetch_rss_feed(feed_cfg: dict) -> list[RawArticle]:
    if not feed_cfg.get("enabled", True):
        return []

    name = feed_cfg.get("name", "unknown")
    url = feed_cfg.get("url", "")
    if not url:
        return []

    try:
        resp = httpx.get(
            url,
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        articles = _parse_feed_xml(resp.content, feed_cfg)
        logger.info("RSS [%s]: fetched %d articles", name, len(articles))
        return articles
    except Exception as exc:
        logger.warning("RSS fetch failed [%s]: %s", name, exc)
        return []


def _collection_settings() -> dict:
    return load_yaml("settings.yaml").get("collection", {})


def fetch_all_rss() -> list[RawArticle]:
    cfg = load_yaml("rss_feeds.yaml")
    feeds = [f for f in cfg.get("feeds", []) if f.get("enabled", True)]
    if not feeds:
        return []

    workers = min(_collection_settings().get("rss_workers", 6), len(feeds))
    results: list[RawArticle] = []

    if workers <= 1:
        for feed in feeds:
            results.extend(fetch_rss_feed(feed))
        return results

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_rss_feed, feed): feed for feed in feeds}
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception as exc:
                feed = futures[future]
                logger.warning("RSS worker failed [%s]: %s", feed.get("name"), exc)

    return results


def feed_source_score_boost(feed_cfg: dict) -> bool:
    return bool(feed_cfg.get("official"))
