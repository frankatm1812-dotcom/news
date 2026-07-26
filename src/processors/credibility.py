"""Assign credibility labels based on source coverage."""

from __future__ import annotations

import logging

from src.models import ProcessedArticle
from src.processors.source_authority import get_source_score, is_official_source

logger = logging.getLogger(__name__)


def _format_label(level: str, source_count: int) -> str:
    if level == "green":
        return f"🟢 已确认（{source_count}个来源）"
    if level == "yellow":
        return f"🟡 多方报道（{source_count}源）但未证实"
    return "🔴 单一来源"


def assign_credibility(articles: list[ProcessedArticle]) -> list[ProcessedArticle]:
    for art in articles:
        sources = art.cluster_sources or [art.source]
        unique_sources = list(dict.fromkeys(s for s in sources if s))
        if not unique_sources:
            unique_sources = [art.source]
        source_count = len(unique_sources)
        art.cluster_sources = unique_sources

        tier_s_sources = [s for s in unique_sources if get_source_score(s) >= 90]
        has_tier_s = len(tier_s_sources) > 0
        has_official = any(is_official_source(s, art.url) for s in unique_sources)

        if source_count >= 2 and (has_official or has_tier_s):
            art.credibility = "green"
        elif source_count >= 2:
            art.credibility = "yellow"
        else:
            art.credibility = "red"

        art.credibility_label = _format_label(art.credibility, source_count)

    logger.info(
        "Credibility: green=%d yellow=%d red=%d",
        sum(1 for a in articles if a.credibility == "green"),
        sum(1 for a in articles if a.credibility == "yellow"),
        sum(1 for a in articles if a.credibility == "red"),
    )
    return articles
