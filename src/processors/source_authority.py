"""Source authority scoring."""

from __future__ import annotations

import re

from src.config_loader import load_yaml


def _load_source_scores() -> tuple[dict[str, int], list[str], int]:
    cfg = load_yaml("sources.yaml")
    scores: dict[str, int] = {}
    for tier_name, tier in cfg["tiers"].items():
        score = tier["score"]
        for source in tier["sources"]:
            scores[source.lower()] = score
    official_patterns = cfg.get("official_patterns", [])
    default_score = cfg.get("default_score", 40)
    return scores, official_patterns, default_score


_SOURCE_SCORES, _OFFICIAL_PATTERNS, _DEFAULT_SCORE = _load_source_scores()


def get_source_score(source: str) -> int:
    key = source.strip().lower()
    if key in _SOURCE_SCORES:
        return _SOURCE_SCORES[key]
    for name, score in _SOURCE_SCORES.items():
        if name in key or key in name:
            return score
    return _DEFAULT_SCORE


def is_official_source(source: str, url: str = "") -> bool:
    text = f"{source} {url}".lower()
    for pattern in _OFFICIAL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False
