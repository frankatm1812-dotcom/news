"""Generate executive summary highlights for the briefing."""

from __future__ import annotations

import json
import logging

from src.config_loader import load_yaml
from src.models import ProcessedArticle
from src.processors import llm_client

logger = logging.getLogger(__name__)


def _importance_score(art: ProcessedArticle) -> tuple:
    source_count = len(art.cluster_sources or [art.source])
    return (source_count, art.source_score, art.published_at)


def _highlights_rules(articles: list[ProcessedArticle]) -> str:
    if not articles:
        return "过去12小时内暂无符合条件的新闻。"

    ranked = sorted(articles, key=_importance_score, reverse=True)
    lines = []
    for art in ranked[:5]:
        fact = next((f for f in art.facts_zh if f.strip()), art.title_zh)
        source_note = ""
        if len(art.cluster_sources) > 1:
            source_note = f"（{len(art.cluster_sources)}源报道）"
        lines.append(f"{len(lines) + 1}. [{art.topic}] {art.title_zh}{source_note}：{fact}")
    return "\n".join(lines)


def generate_highlights(articles: list[ProcessedArticle]) -> str:
    if not articles:
        return _highlights_rules(articles)

    use_llm = load_yaml("settings.yaml").get("processing", {}).get("use_llm_highlights", False)
    if use_llm and llm_client.is_available():
        try:
            payload = [
                {
                    "topic": a.topic,
                    "title": a.title_zh,
                    "source": a.source,
                    "credibility": a.credibility_label,
                    "facts": [f for f in a.facts_zh if f.strip()],
                    "sources_count": len(a.cluster_sources or [a.source]),
                }
                for a in articles
            ]
            prompt = f"""你是新闻编辑。根据以下简报条目，撰写「今日要点」总览。

要求：
1. 用中文，3-5 句，每句一句
2. 覆盖 AI 和地缘政治两个主题的重要进展
3. 客观陈述，不加评论
4. 直接输出要点文本，不要标题、不要 markdown

新闻条目：
{json.dumps(payload, ensure_ascii=False)}"""

            text = llm_client.generate_text(prompt).strip()
            if text:
                logger.info("Generated highlights via Groq")
                return text
        except Exception as exc:
            logger.warning("Groq highlights failed, using rules: %s", exc)

    return _highlights_rules(articles)
