"""Rule-based fallback: translation, summarization, classification, dedup."""

from __future__ import annotations

import logging
import re
from html import unescape

from deep_translator import GoogleTranslator
from rapidfuzz import fuzz

from src.config_loader import load_yaml
from src.models import ProcessedArticle, RawArticle
from src.processors.source_authority import get_source_score

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 85

LANG_CODES = {
    "zh": "zh-CN",
    "en": "en",
    "fr": "fr",
    "de": "de",
    "ja": "ja",
    "es": "es",
    "ar": "ar",
}

_topic_keywords: dict[str, list[str]] | None = None


def _load_topic_keywords() -> dict[str, list[str]]:
    global _topic_keywords
    if _topic_keywords is not None:
        return _topic_keywords

    cfg = load_yaml("keywords.yaml")
    result: dict[str, list[str]] = {}
    for topic in cfg["topics"]:
        words: list[str] = []
        for lang_words in topic["keywords"].values():
            words.extend(lang_words)
        result[topic["name"]] = list(dict.fromkeys(words))
    _topic_keywords = result
    return result


def strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return unescape(re.sub(r"\s+", " ", cleaned)).strip()


def translate_to_zh(text: str, source_lang: str) -> str:
    if not text.strip() or source_lang == "zh":
        return text.strip()
    try:
        src = LANG_CODES.get(source_lang, "auto")
        return GoogleTranslator(source=src, target="zh-CN").translate(text[:5000])
    except Exception as exc:
        logger.debug("Translation failed [%s]: %s", source_lang, exc)
        return text.strip()


def classify_topic(title: str, body: str, hint: str) -> str:
    keywords_map = _load_topic_keywords()
    text = f"{title} {body}".lower()
    scores: dict[str, int] = {}
    for topic, keywords in keywords_map.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        scores[topic] = score
    best = max(scores, key=scores.get) if scores else hint
    return best if scores.get(best, 0) > 0 else hint


def extract_facts_zh(title: str, body: str, summary: str, lang: str) -> list[str]:
    raw = body or strip_html(summary) or title
    parts = re.split(r"(?<=[.!?。！？])\s+", raw)
    sentences = [p.strip() for p in parts if len(p.strip()) > 12][:3]

    if not sentences:
        sentences = [title]

    if lang != "zh":
        sentences = [translate_to_zh(s, lang) for s in sentences]

    while len(sentences) < 3:
        sentences.append("")
    return sentences[:3]


def extract_article_rules(art: RawArticle, body: str = "") -> ProcessedArticle:
    title_original = art.title.strip()
    title_zh = translate_to_zh(title_original, art.language) if art.language != "zh" else title_original
    topic = classify_topic(title_original, body, art.topic_hint)
    facts = extract_facts_zh(title_original, body, art.summary, art.language)

    return ProcessedArticle(
        title_original=title_original,
        title_zh=title_zh,
        url=art.url,
        source=art.source,
        source_score=get_source_score(art.source),
        published_at=art.published_at,
        language=art.language,
        topic=topic,
        facts_zh=facts,
        credibility="red",
        credibility_label="🔴 单一来源",
        all_titles={art.language: title_original},
    )


def extract_batch_rules(articles: list[RawArticle], bodies: dict[int, str] | None = None) -> list[ProcessedArticle]:
    bodies = bodies or {}
    logger.info("Rule engine: extracting %d articles", len(articles))
    return [extract_article_rules(art, bodies.get(i, "")) for i, art in enumerate(articles)]


def _pick_representative(articles: list[ProcessedArticle], member_ids: list[int]) -> int:
    return max(member_ids, key=lambda i: (articles[i].source_score, len(articles[i].facts_zh[0])))


def deduplicate_rules(articles: list[ProcessedArticle]) -> list[ProcessedArticle]:
    if len(articles) <= 1:
        if articles:
            articles[0].cluster_sources = [articles[0].source]
        return articles

    logger.info("Rule engine: deduplicating %d articles", len(articles))
    clusters: list[list[int]] = []
    assigned: set[int] = set()

    for i, art in enumerate(articles):
        if i in assigned:
            continue
        cluster = [i]
        assigned.add(i)
        for j, other in enumerate(articles):
            if j in assigned or art.topic != other.topic:
                continue
            score = fuzz.token_set_ratio(art.title_zh, other.title_zh)
            if score >= SIMILARITY_THRESHOLD:
                cluster.append(j)
                assigned.add(j)
        clusters.append(cluster)

    result: list[ProcessedArticle] = []
    for idx, member_ids in enumerate(clusters):
        rep_id = _pick_representative(articles, member_ids)
        rep = articles[rep_id]
        rep.cluster_id = f"r{idx}"
        rep.cluster_sources = list(dict.fromkeys(articles[m].source for m in member_ids))
        rep.all_titles = {}
        for m in member_ids:
            a = articles[m]
            rep.all_titles[a.language] = a.title_original
        result.append(rep)

    logger.info("Rule engine dedup: %d -> %d articles", len(articles), len(result))
    return result
