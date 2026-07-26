"""Article extraction: Groq LLM primary, rule engine fallback."""

from __future__ import annotations

import json
import logging
import re

import trafilatura

from src.models import ProcessedArticle, RawArticle
from src.processors import llm_client
from src.processors.rule_engine import extract_batch_rules
from src.processors.source_authority import get_source_score

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


def fetch_article_text(url: str, fallback: str = "") -> str:
    if "news.google.com/rss/articles" in url or "news.google.com/articles" in url:
        return fallback[:2000] if fallback else ""

    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if text and len(text.strip()) > 80:
                return text[:4000]
    except Exception as exc:
        logger.debug("trafilatura failed for %s: %s", url, exc)
    return fallback[:2000] if fallback else ""


def _parse_json_response(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _build_results(articles: list[RawArticle], items: list) -> list[ProcessedArticle]:
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
                url=art.url,
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


def extract_batch_llm(articles: list[RawArticle]) -> list[ProcessedArticle]:
    bodies: dict[int, str] = {}
    payload = []
    for i, art in enumerate(articles):
        body = fetch_article_text(art.url, art.summary)
        bodies[i] = body
        payload.append(
            {
                "id": i,
                "title": art.title,
                "language": art.language,
                "language_name": LANGUAGE_NAMES.get(art.language, art.language),
                "source": art.source,
                "published_at": art.published_at.isoformat(),
                "url": art.url,
                "topic_hint": art.topic_hint,
                "body": body[:2500],
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
    return _build_results(articles, items)


def extract_batch(articles: list[RawArticle]) -> list[ProcessedArticle]:
    if not articles:
        return []

    bodies = {i: fetch_article_text(art.url, art.summary) for i, art in enumerate(articles)}

    if llm_client.is_available():
        try:
            return extract_batch_llm(articles)
        except Exception as exc:
            logger.warning("Groq extraction failed, falling back to rules: %s", exc)

    return extract_batch_rules(articles, bodies)


def extract_all(articles: list[RawArticle], batch_size: int = 5) -> list[ProcessedArticle]:
    all_processed: list[ProcessedArticle] = []
    for start in range(0, len(articles), batch_size):
        batch = articles[start : start + batch_size]
        logger.info("Extracting batch %d-%d / %d", start + 1, start + len(batch), len(articles))
        all_processed.extend(extract_batch(batch))
    return all_processed
