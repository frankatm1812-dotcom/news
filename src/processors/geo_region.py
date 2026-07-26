"""Classify geopolitics articles by region."""

from __future__ import annotations

import logging

from src.config_loader import load_yaml
from src.models import ProcessedArticle

logger = logging.getLogger(__name__)

_GEO_CONFIG: dict | None = None


def _load_config() -> tuple[list[str], dict[str, list[str]]]:
    global _GEO_CONFIG
    if _GEO_CONFIG is not None:
        cfg = _GEO_CONFIG
        return cfg["priority"], cfg["regions"]

    raw = load_yaml("geo_regions.yaml")
    priority = raw.get("priority", ["俄乌", "中东", "东亚", "美国", "非洲", "欧洲", "其他"])
    regions = {name: list(keywords) for name, keywords in raw.get("regions", {}).items()}
    if "其他" not in regions:
        regions["其他"] = []
    _GEO_CONFIG = {"priority": priority, "regions": regions}
    return priority, regions


def _article_text(art: ProcessedArticle) -> str:
    parts = [art.title_original, art.title_zh, art.url, " ".join(art.facts_zh)]
    return " ".join(p for p in parts if p).lower()


def classify_geo_region(art: ProcessedArticle) -> str:
    if art.topic != "地缘政治":
        return ""

    priority, regions = _load_config()
    text = _article_text(art)

    scores: dict[str, int] = {}
    for name, keywords in regions.items():
        if name == "其他":
            continue
        scores[name] = sum(1 for kw in keywords if kw.lower() in text)

    best = max(scores.values()) if scores else 0
    if best == 0:
        return "其他"

    tied = [name for name, score in scores.items() if score == best]
    for name in priority:
        if name in tied:
            return name
    return tied[0]


def assign_geo_regions(articles: list[ProcessedArticle]) -> list[ProcessedArticle]:
    counts: dict[str, int] = {}
    for art in articles:
        if art.topic == "地缘政治":
            art.region = classify_geo_region(art)
            counts[art.region] = counts.get(art.region, 0) + 1
        else:
            art.region = ""

    if counts:
        summary = "、".join(f"{k}:{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
        logger.info("Geo regions: %s", summary)
    return articles
