"""Assign credibility labels based on source coverage."""

from __future__ import annotations

import logging

from src.models import ProcessedArticle
from src.processors.source_authority import get_source_score, is_official_source

logger = logging.getLogger(__name__)

LABELS = {
    "red": "🔴 单一来源",
    "yellow": "🟡 多方报道但未证实",
    "green": "🟢 已确认",
}


def assign_credibility(articles: list[ProcessedArticle]) -> list[ProcessedArticle]:
    for art in articles:
        sources = art.cluster_sources or [art.source]
        unique_sources = list(dict.fromkeys(sources))
        source_count = len(unique_sources)

        has_tier_s = any(get_source_score(src) >= 90 for src in unique_sources)
        has_official = any(is_official_source(src, art.url) for src in unique_sources)

        if source_count >= 2 and (has_official or has_tier_s):
            art.credibility = "green"
        elif source_count >= 2:
            art.credibility = "yellow"
        else:
            art.credibility = "red"

        art.credibility_label = LABELS[art.credibility]

    logger.info(
        "Credibility: green=%d yellow=%d red=%d",
        sum(1 for a in articles if a.credibility == "green"),
        sum(1 for a in articles if a.credibility == "yellow"),
        sum(1 for a in articles if a.credibility == "red"),
    )
    return articles
