"""Weekly trend analysis: rules primary, Groq optional."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from src.config_loader import load_yaml
from src.models import ProcessedArticle
from src.processors import llm_client

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))


def _beijing_day(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d")


def _topic_counts(articles: list[ProcessedArticle]) -> Counter:
    return Counter(a.topic for a in articles if a.topic)


def _credibility_counts(articles: list[ProcessedArticle]) -> Counter:
    return Counter(a.credibility for a in articles)


def _daily_topic_counts(articles: list[ProcessedArticle]) -> dict[str, Counter]:
    by_day: dict[str, Counter] = defaultdict(Counter)
    for art in articles:
        by_day[_beijing_day(art.published_at)][art.topic] += 1
    return dict(by_day)


def _compare_halves(articles: list[ProcessedArticle]) -> list[dict]:
    if len(articles) < 4:
        return []

    sorted_arts = sorted(articles, key=lambda a: a.published_at)
    mid = len(sorted_arts) // 2
    first = sorted_arts[:mid]
    second = sorted_arts[mid:]

    first_counts = _topic_counts(first)
    second_counts = _topic_counts(second)
    topics = set(first_counts) | set(second_counts)

    trends = []
    for topic in sorted(topics):
        a = first_counts.get(topic, 0)
        b = second_counts.get(topic, 0)
        if b > a * 1.2:
            label = "升温"
        elif b < a * 0.8:
            label = "降温"
        else:
            label = "平稳"
        trends.append({"topic": topic, "first_half": a, "second_half": b, "trend": label})
    return trends


def _top_events(articles: list[ProcessedArticle], limit: int = 8) -> list[ProcessedArticle]:
    return sorted(
        articles,
        key=lambda a: (len(a.cluster_sources or []), a.source_score, a.published_at),
        reverse=True,
    )[:limit]


def _top_sources(articles: list[ProcessedArticle], limit: int = 8) -> list[tuple[str, int]]:
    counter = Counter(a.source for a in articles)
    return counter.most_common(limit)


def analyze_trends_rules(articles: list[ProcessedArticle], days: int = 7) -> dict:
    topic_counts = _topic_counts(articles)
    cred_counts = _credibility_counts(articles)
    daily = _daily_topic_counts(articles)
    half_trends = _compare_halves(articles)
    top_events = _top_events(articles)
    top_sources = _top_sources(articles)

    lines = [
        f"过去 {days} 天共收录 {len(articles)} 条去重新闻。",
    ]

    if topic_counts:
        parts = [f"{t} {c}条" for t, c in topic_counts.most_common()]
        lines.append(f"主题分布：{'、'.join(parts)}。")

    if cred_counts:
        green = cred_counts.get("green", 0)
        yellow = cred_counts.get("yellow", 0)
        red = cred_counts.get("red", 0)
        lines.append(f"可信度：🟢 {green} 条、🟡 {yellow} 条、🔴 {red} 条。")

    for item in half_trends:
        lines.append(
            f"「{item['topic']}」后半周 {item['second_half']} 条 vs 前半周 {item['first_half']} 条，趋势{item['trend']}。"
        )

    if top_events:
        lines.append("本周重要事件：")
        for i, art in enumerate(top_events[:5], 1):
            src_note = f"（{len(art.cluster_sources)}源）" if len(art.cluster_sources) > 1 else ""
            lines.append(f"{i}. [{art.topic}] {art.title_zh}{src_note}")

    return {
        "summary_lines": lines,
        "topic_counts": dict(topic_counts),
        "credibility_counts": dict(cred_counts),
        "daily_topic_counts": {day: dict(c) for day, c in sorted(daily.items())},
        "half_trends": half_trends,
        "top_events": top_events,
        "top_sources": top_sources,
    }


def analyze_trends(articles: list[ProcessedArticle], days: int = 7) -> dict:
    rules_result = analyze_trends_rules(articles, days=days)

    use_llm = load_yaml("settings.yaml").get("weekly", {}).get("use_llm_analysis", True)
    if not use_llm or not llm_client.is_available() or not articles:
        return rules_result

    try:
        payload = {
            "days": days,
            "total": len(articles),
            "topic_counts": rules_result["topic_counts"],
            "credibility_counts": rules_result["credibility_counts"],
            "half_trends": rules_result["half_trends"],
            "top_titles": [a.title_zh for a in rules_result["top_events"][:10]],
            "top_sources": rules_result["top_sources"],
        }
        prompt = f"""你是新闻分析编辑。根据以下过去{days}天的新闻统计数据，撰写中文「趋势分析」。

要求：
1. 4-6 句，覆盖 AI 与地缘政治两大主题
2. 指出升温/降温/持续热点
3. 客观陈述，不加评论
4. 直接输出分析段落，不要标题、不要 markdown

统计数据：
{json.dumps(payload, ensure_ascii=False)}"""

        text = llm_client.generate_text(prompt).strip()
        if text:
            rules_result["summary_lines"] = [text]
            rules_result["llm_enhanced"] = True
            logger.info("Weekly trend analysis enhanced via Groq")
    except Exception as exc:
        logger.warning("Groq weekly analysis failed, using rules: %s", exc)

    return rules_result
