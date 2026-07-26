from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawArticle:
    title: str
    url: str
    source: str
    published_at: datetime
    language: str
    topic_hint: str
    summary: str = ""
    collector: str = "google_news"


@dataclass
class ProcessedArticle:
    title_original: str
    title_zh: str
    url: str
    source: str
    source_score: int
    published_at: datetime
    language: str
    topic: str
    facts_zh: list[str]
    credibility: str  # red, yellow, green
    credibility_label: str
    region: str = ""
    cluster_id: Optional[str] = None
    cluster_sources: list[str] = field(default_factory=list)
    all_titles: dict[str, str] = field(default_factory=dict)
