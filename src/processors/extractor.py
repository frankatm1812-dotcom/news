"""Article extraction: Groq LLM primary, rule engine fallback."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
import trafilatura

from src.config_loader import load_yaml
from src.models import ProcessedArticle, RawArticle
from src.processors import llm_client
from src.processors.rule_engine import extract_batch_rules, strip_html
from src.processors.source_authority import get_source_score
from src.processors.url_resolver import resolve_urls_batch

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "zh": "中文",
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "ja": "日本語",
    "es": "Español",
    "ar": "العربية",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _processing_settings() -> dict:
    return load_yaml("settings.yaml").get("processing", {})


def fetch_article_text(url: str, fallback: str = "") -> str:
    clean_fallback = strip_html(fallback)
    min_summary = _processing_settings().get("skip_fetch_min_summary_len", 150)
    if clean_fallback and len(clean_fallback) >= min_summary:
        return clean_fallback[:4000]

    if not url or _is_blocked_url(url):
        return clean_fallback[:2000] if clean_fallback else ""

    timeout = _processing_settings().get("fetch_timeout_sec", 10)
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        if resp.status_code != 200:
            logger.debug("Fetch %s returned %s", url[:80], resp.status_code)
            return clean_fallback[:2000] if clean_fallback else ""

        text = trafilatura.extract(
            resp.text,
            include_comments=False,
            include_tables=False,
        )
        if text and len(text.strip()) > 80:
            return text[:4000]
    except Exception as exc:
        logger.debug("Fetch failed for %s: %s", url[:80], exc)

    return clean_fallback[:2000] if clean_fallback else ""


def _is_blocked_url(url: str) -> bool:
    return "news.google.com" in url


def _resolve_and_fetch_one(index: int, url: str, fallback: str) -> tuple[int, str, str]:
    return index, url, fetch_article_text(url, fallback)


def prepare_batch_content(articles: list[RawArticle]) -> tuple[dict[int, str], dict[int, str]]:
    """Resolve URLs once and fetch bodies in parallel."""
    resolved_list = resolve_urls_batch([art.url for art in articles])
    resolved_urls = {i: resolved_list[i] for i in range(len(articles))}

    workers = min(_processing_settings().get("fetch_workers", 4), len(articles))
    bodies: dict[int, str] = {}

    if workers <= 1:
        for i, art in enumerate(articles):
            bodies[i] = fetch_article_text(resolved_urls[i], art.summary)
        return resolved_urls, bodies

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_resolve_and_fetch_one, i, resolved_urls[i], art.summary)
            for i, art in enumerate(articles)
        ]
        for future in futures:
            i, resolved, body = future.result()
            resolved_urls[i] = resolved
            bodies[i] = body

    return resolved_urls, bodies


def _parse_json_response(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _build_results(
    articles: list[RawArticle],
    items: list,
    resolved_urls: dict[int, str],
) -> list[ProcessedArticle]:
    by_id = {item["id"]: item for item in items if isinstance(item, dict) and "id" in item}
    results: list[ProcessedArticle] = []

    for i, art in enumerate(articles):
        item = by_id.get(i, {})
        facts = item.get("facts_zh") or [art.title]
        while len(facts) < 3:
            facts.append("")
        facts = facts[:3]

        results.append(
            ProcessedArticle(
                title_original=item.get("title_original") or art.title,
                title_zh=item.get("title_zh") or art.title,
                url=resolved_urls.get(i, art.url),
                source=art.source,
                source_score=get_source_score(art.source),
                published_at=art.published_at,
                language=art.language,
                topic=item.get("topic") or art.topic_hint,
                facts_zh=facts,
                credibility="red",
                credibility_label="🔴 单一来源",
                all_titles={art.language: item.get("title_original") or art.title},
            )
        )
    return results


def extract_batch_llm(
    articles: list[RawArticle],
    resolved_urls: dict[int, str],
    bodies: dict[int, str],
) -> list[ProcessedArticle]:
    payload = []
    for i, art in enumerate(articles):
        payload.append(
            {
                "id": i,
                "title": art.title,
                "language": art.language,
                "language_name": LANGUAGE_NAMES.get(art.language, art.language),
                "source": art.source,
                "published_at": art.published_at.isoformat(),
                "url": resolved_urls[i],
                "topic_hint": art.topic_hint,
                "body": bodies.get(i, "")[:2500],
            }
        )

    prompt = f"""你是新闻分析助手。对以下新闻条目逐条处理，输出 JSON 数组。

要求：
1. title_original: 保留原文标题
2. title_zh: 中文标题（若原文为中文则与原文相同）
3. facts_zh: 恰好3句中文核心事实，客观、无评论
4. topic: 从 ["AI", "地缘政治"] 中选择最匹配的一个
5. 仅基于提供的正文/摘要，不要编造

输入：
{json.dumps(payload, ensure_ascii=False)}

输出格式（纯 JSON 数组，无 markdown）：
[
  {{
    "id": 0,
    "title_original": "...",
    "title_zh": "...",
    "facts_zh": ["...", "...", "..."],
    "topic": "AI"
  }}
]"""

    response_text = llm_client.generate_text(prompt)
    items = _parse_json_response(response_text)
    logger.info("Groq LLM: extracted batch of %d", len(articles))
    return _build_results(articles, items, resolved_urls)


def extract_batch(articles: list[RawArticle]) -> list[ProcessedArticle]:
    if not articles:
        return []

    resolved_urls, bodies = prepare_batch_content(articles)

    if llm_client.is_available():
        try:
            return extract_batch_llm(articles, resolved_urls, bodies)
        except Exception as exc:
            logger.warning("Groq extraction failed, falling back to rules: %s", exc)

    results = extract_batch_rules(articles, bodies)
    for i, art in enumerate(results):
        art.url = resolved_urls.get(i, art.url)
    return results


def extract_all(articles: list[RawArticle], batch_size: int | None = None) -> list[ProcessedArticle]:
    if batch_size is None:
        batch_size = _processing_settings().get("extract_batch_size", 5)

    all_processed: list[ProcessedArticle] = []
    for start in range(0, len(articles), batch_size):
        batch = articles[start : start + batch_size]
        logger.info("Extracting batch %d-%d / %d", start + 1, start + len(batch), len(articles))
        all_processed.extend(extract_batch(batch))
    return all_processed
