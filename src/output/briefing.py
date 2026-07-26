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

GEO_REGION_ORDER = ["东亚", "中东", "俄乌", "欧洲", "美国", "非洲", "其他"]


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
    region_note = ""
    if art.region:
        region_note = f'<span style="color:#0369a1;font-size:12px;margin-right:6px;">[{art.region}]</span>'

    return f"""
    <div style="margin-bottom:20px;padding:12px;border-left:4px solid #2563eb;background:#f8fafc;">
      <p style="margin:0 0 6px;font-size:15px;">
        {art.credibility_label}
        {region_note}
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


def _render_geo_section(items: list[ProcessedArticle]) -> str:
    by_region: dict[str, list[ProcessedArticle]] = defaultdict(list)
    for art in items:
        by_region[art.region or "其他"].append(art)

    html = ""
    for region in GEO_REGION_ORDER:
        region_items = by_region.get(region, [])
        if not region_items:
            continue
        region_items.sort(key=lambda a: a.published_at, reverse=True)
        html += f"""
        <h3 style="color:#334155;margin:16px 0 8px;font-size:15px;">🌏 {region} ({len(region_items)}条)</h3>
        {''.join(_render_article(a) for a in region_items)}
        """
    return html


def _render_highlights(highlights: str) -> str:
    if not highlights.strip():
        return ""
    paragraphs = [p.strip() for p in highlights.replace("\n\n", "\n").split("\n") if p.strip()]
    body = "".join(f"<p style='margin:0 0 8px;font-size:14px;line-height:1.6;'>{p}</p>" for p in paragraphs)
    return f"""
  <div style="background:#eff6ff;border-radius:8px;padding:16px;margin-bottom:20px;">
    <h2 style="margin:0 0 10px;font-size:16px;color:#1e40af;">📌 今日要点</h2>
    {body}
  </div>
  """


def generate_html(
    articles: list[ProcessedArticle],
    raw_count: int,
    filtered_count: int,
    highlights: str = "",
    window_hours: int = 12,
) -> str:
    now_bj = datetime.now(BEIJING_TZ)
    window_start = now_bj - timedelta(hours=window_hours)
    grouped: dict[str, list[ProcessedArticle]] = defaultdict(list)
    for art in articles:
        topic = art.topic if art.topic == "地缘政治" else "其他"
        grouped[topic].append(art)

    for topic in grouped:
        grouped[topic].sort(key=lambda a: a.published_at, reverse=True)

    topic_order = ["地缘政治", "其他"]
    sections_html = ""
    for topic in topic_order:
        items = grouped.get(topic, [])
        if not items:
            continue
        if topic == "地缘政治":
            articles_html = _render_geo_section(items)
        else:
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

    highlights_html = _render_highlights(highlights)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>新闻简报</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:720px;margin:0 auto;padding:20px;color:#1e293b;">
  <h1 style="color:#0f172a;">📰 新闻简报</h1>
  <p style="color:#64748b;">
    {now_bj.strftime("%Y-%m-%d %H:%M")} (北京时间)<br>
    时间窗口: {window_start.strftime("%m-%d %H:%M")} ~ {now_bj.strftime("%m-%d %H:%M")} (近{window_hours}小时)<br>
    本次共收录 <strong>{len(articles)}</strong> 条 |
    去重前 {filtered_count} 条 |
    采集 {raw_count} 条 |
    覆盖语种: {", ".join(LANG_LABELS.get(l, l) for l in langs) or "无"}
  </p>
  {highlights_html}
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
