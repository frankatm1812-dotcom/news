"""Generate HTML email briefing."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta

from src.models import ProcessedArticle

BEIJING_TZ = timezone(timedelta(hours=8))

LANG_LABELS = {
    "zh": "中文",
    "en": "English",
    "fr": "Français",
    "de": "Deutsch",
    "ja": "日本語",
    "es": "Español",
    "ar": "العربية",
}


def _format_beijing_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


def _render_titles(all_titles: dict[str, str]) -> str:
    if not all_titles:
        return ""
    parts = []
    for lang, title in sorted(all_titles.items()):
        label = LANG_LABELS.get(lang, lang)
        parts.append(f"<em>{label}</em>: {title}")
    return "<br>".join(parts)


def _render_article(art: ProcessedArticle) -> str:
    facts_html = "".join(f"<li>{fact}</li>" for fact in art.facts_zh if fact.strip())
    titles_html = _render_titles(art.all_titles)
    sources_note = ""
    if len(art.cluster_sources) > 1:
        sources_note = f"<br><small>报道来源: {', '.join(art.cluster_sources)}</small>"

    return f"""
    <div style="margin-bottom:20px;padding:12px;border-left:4px solid #2563eb;background:#f8fafc;">
      <p style="margin:0 0 6px;font-size:15px;">
        {art.credibility_label}
        <strong>[{art.source}]</strong> {art.title_zh}
      </p>
      <p style="margin:0 0 6px;color:#64748b;font-size:13px;">
        发布时间: {_format_beijing_time(art.published_at)} (北京时间)
        {sources_note}
      </p>
      <p style="margin:0 0 6px;font-size:13px;color:#475569;">{titles_html}</p>
      <ul style="margin:8px 0;padding-left:20px;font-size:14px;">{facts_html}</ul>
      <p style="margin:0;"><a href="{art.url}" style="color:#2563eb;">阅读原文</a></p>
    </div>
    """


def generate_html(
    articles: list[ProcessedArticle],
    raw_count: int,
    filtered_count: int,
) -> str:
    now_bj = datetime.now(BEIJING_TZ)
    grouped: dict[str, list[ProcessedArticle]] = defaultdict(list)
    for art in articles:
        topic = art.topic if art.topic in ("AI", "地缘政治") else "其他"
        grouped[topic].append(art)

    for topic in grouped:
        grouped[topic].sort(key=lambda a: a.published_at, reverse=True)

    topic_order = ["AI", "地缘政治", "其他"]
    sections_html = ""
    for topic in topic_order:
        items = grouped.get(topic, [])
        if not items:
            continue
        articles_html = "".join(_render_article(a) for a in items)
        sections_html += f"""
        <h2 style="color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:6px;">
          📂 {topic} ({len(items)}条)
        </h2>
        {articles_html}
        """

    if not sections_html:
        sections_html = "<p>过去12小时内未找到符合条件的新闻。</p>"

    langs = sorted({a.language for a in articles})

    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>新闻简报</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:720px;margin:0 auto;padding:20px;color:#1e293b;">
  <h1 style="color:#0f172a;">📰 新闻简报</h1>
  <p style="color:#64748b;">
    {now_bj.strftime("%Y-%m-%d %H:%M")} (北京时间)<br>
    本次共收录 <strong>{len(articles)}</strong> 条 |
    去重前 {filtered_count} 条 |
    采集 {raw_count} 条 |
    覆盖语种: {", ".join(LANG_LABELS.get(l, l) for l in langs) or "无"}
  </p>
  <hr style="border:none;border-top:1px solid #e2e8f0;">
  {sections_html}
  <hr style="border:none;border-top:1px solid #e2e8f0;">
  <p style="color:#94a3b8;font-size:12px;">
    可信度说明:
    🔴 单一来源 | 🟡 多方报道但未证实 | 🟢 已确认<br>
    本简报由自动化工作流生成，仅供参考。
  </p>
</body>
</html>"""


def generate_subject(articles: list[ProcessedArticle]) -> str:
    now_bj = datetime.now(BEIJING_TZ)
    slot = "早报" if now_bj.hour < 12 else "晚报"
    return f"📰 新闻简报 {slot} | {now_bj.strftime('%Y-%m-%d %H:%M')} | {len(articles)}条"
