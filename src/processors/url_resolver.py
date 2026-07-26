"""Resolve Google News redirect URLs to original article links."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from src.config_loader import load_yaml

logger = logging.getLogger(__name__)

_decode_lock = threading.Lock()
_last_decode_at = 0.0
_url_cache: dict[str, str] = {}


def _processing_settings() -> dict:
    return load_yaml("settings.yaml").get("processing", {})


def _decode_interval() -> float:
    return _processing_settings().get("google_news_decode_interval", 0.3)


def _is_google_news_url(url: str) -> bool:
    return "news.google.com" in url


def resolve_google_news_url(url: str) -> str:
    """Return decoded original URL, or the input URL if decoding fails."""
    global _last_decode_at

    if not url:
        return url

    cached = _url_cache.get(url)
    if cached:
        return cached

    if not _is_google_news_url(url):
        _url_cache[url] = url
        return url

    with _decode_lock:
        elapsed = time.time() - _last_decode_at
        wait = _decode_interval() - elapsed
        if wait > 0:
            time.sleep(wait)

        try:
            from googlenewsdecoder import gnewsdecoder

            result = gnewsdecoder(url, interval=None)
            _last_decode_at = time.time()
            if result.get("status") and result.get("decoded_url"):
                decoded = result["decoded_url"]
                _url_cache[url] = decoded
                logger.debug("Decoded URL: %s -> %s", url[:60], decoded[:60])
                return decoded
            logger.debug("Decode failed: %s", result.get("message", "unknown"))
        except Exception as exc:
            logger.debug("googlenewsdecoder error: %s", exc)

    try:
        resp = httpx.get(url, follow_redirects=True, timeout=10.0)
        final = str(resp.url)
        if not _is_google_news_url(final):
            _url_cache[url] = final
            return final
    except Exception as exc:
        logger.debug("Redirect follow failed: %s", exc)

    _url_cache[url] = url
    return url


def resolve_urls_batch(urls: list[str]) -> list[str]:
    """Resolve multiple Google News URLs, using a small worker pool."""
    if not urls:
        return []

    unique = list(dict.fromkeys(urls))
    workers = min(_processing_settings().get("url_resolve_workers", 4), len(unique))
    if workers <= 1:
        resolved = [resolve_google_news_url(u) for u in unique]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            resolved = list(pool.map(resolve_google_news_url, unique))

    mapping = dict(zip(unique, resolved))
    return [mapping[u] for u in urls]
