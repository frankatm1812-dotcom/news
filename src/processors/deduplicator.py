"""Event deduplication: rule engine primary, optional Groq refinement."""

from __future__ import annotations

import json
import logging
import re

from src.config_loader import load_yaml
from src.models import ProcessedArticle
from src.processors import llm_client
from src.processors.rule_engine import deduplicate_rules

logger = logging.getLogger(__name__)


def _parse_json_response(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _apply_llm_clusters(articles: list[ProcessedArticle], clusters: list) -> list[ProcessedArticle]:
    if not clusters:
        return articles

    kept_ids: set[int] = set()
    result: list[ProcessedArticle] = []

    for cluster in clusters:
        rep_id = cluster.get("representative_id")
        member_ids = cluster.get("member_ids") or [rep_id]
        if rep_id is None or rep_id >= len(articles):
            continue
        if rep_id in kept_ids:
            continue

        rep = articles[rep_id]
        rep.cluster_id = cluster.get("cluster_id", f"c{rep_id}")
        rep.cluster_sources = cluster.get("cluster_sources") or list(
            {articles[i].source for i in member_ids if i < len(articles)}
        )
        rep.all_titles = cluster.get("all_titles") or rep.all_titles

        for lang in {articles[i].language for i in member_ids if i < len(articles)}:
            if lang not in rep.all_titles:
                for i in member_ids:
                    if i < len(articles) and articles[i].language == lang:
                        rep.all_titles[lang] = articles[i].title_original
                        break

        kept_ids.add(rep_id)
        result.append(rep)

    logger.info("Groq LLM dedup: %d -> %d articles", len(articles), len(result))
    return result


def deduplicate_llm(articles: list[ProcessedArticle]) -> list[ProcessedArticle]:
    payload = [
        {
            "id": i,
            "title_zh": a.title_zh,
            "title_original": a.title_original,
            "source": a.source,
            "source_score": a.source_score,
            "language": a.language,
            "url": a.url,
            "topic": a.topic,
        }
        for i, a in enumerate(articles)
    ]

    prompt = f"""你是新闻去重助手。将以下新闻按"同一事件"聚类。

规则：
1. 描述同一事件的新闻归入同一 cluster（包括不同语言报道同一事件）
2. 每个 cluster 选出一条代表新闻：优先权威来源（source_score 高），其次信息更完整
3. 合并同一事件的不同语言标题到 all_titles 字段
4. cluster_sources 列出该事件所有独立来源名称（去重）

输入：
{json.dumps(payload, ensure_ascii=False)}

输出纯 JSON（无 markdown）：
{{
  "clusters": [
    {{
      "cluster_id": "c1",
      "representative_id": 0,
      "member_ids": [0, 3],
      "all_titles": {{"zh": "...", "en": "..."}},
      "cluster_sources": ["Reuters", "BBC"]
    }}
  ]
}}"""

    response_text = llm_client.generate_text(prompt)
    data = _parse_json_response(response_text)
    llm_result = _apply_llm_clusters(articles, data.get("clusters", []))
    return llm_result if llm_result else articles


def deduplicate(articles: list[ProcessedArticle]) -> list[ProcessedArticle]:
    if len(articles) <= 1:
        if articles:
            articles[0].cluster_sources = articles[0].cluster_sources or [articles[0].source]
        return articles

    for a in articles:
        if not a.cluster_sources:
            a.cluster_sources = [a.source]

    use_llm = load_yaml("settings.yaml").get("processing", {}).get("use_llm_dedup", False)
    if use_llm and llm_client.is_available():
        try:
            articles = deduplicate_llm(articles)
        except Exception as exc:
            logger.warning("Groq dedup failed, using rules only: %s", exc)

    refined = deduplicate_rules(articles)
    logger.info("Final dedup: %d articles", len(refined))
    return refined
