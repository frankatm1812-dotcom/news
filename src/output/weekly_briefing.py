"""Generate weekly deep-dive HTML briefing."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from src.models import ProcessedArticle
from src.output.briefing import GEO_REGION_ORDER, LANG_LABELS, _format_beijing_time, _render_titles

BEIJING_TZ = timezone(timedelta(hours=8))


def _render_trend_section(trends: dict) -> str:
    lines = trends.get("summary_lines", [])
    body = "".join(
        f"<p style='margin:0 0 10px;font-size:14px;line-height:1.7;'>{line}</p>"
        for line in lines
    )

    half = trends.get("half_trends", [])
    trend_rows = ""
    for item in half:
        color = {"升温": "#dc2626", "降温": "#2563eb", "平稳": "#64748b"}.get(item["trend"], "#64748b")
        trend_rows += f"""
        <tr>
          <td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;">{item['topic']}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:center;">{item['first_half']}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:center;">{item['second_half']}</td>
          <td style="padding:6px 8px;border-bottom:1px solid #e2e8f0;color:{color};font-weight:600;">{item['trend']}</td>
        </tr>
        """

    table = ""
    if trend_rows:
        table = f"""
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px;">
          <thead>
            <tr style="background:#f1f5f9;">
              <th style="padding:6px 8px;text-align:left;">主题</th>
              <th style="padding:6px 8px;">前半周</th>
              <th style="padding:6px 8px;">后半周</th>
              <th style="padding:6px 8px;">趋势</th>
            </tr>
          </thead>
          <tbody>{trend_rows}</tbody>
        </table>
        """

    daily = trends.get("daily_topic_counts", {})
    daily_lines = []
    for day, counts in daily.items():
        parts = [f"{t}:{n}" for t, n in counts.items()]
        daily_lines.append(f"<li>{day} — {'、'.join(parts)}</li>")
    daily_html = ""
    if daily_lines:
        daily_html = f"""
        <h3 style="margin:16px 0 8px;font-size:14px;color:#475569;">每日主题分布</h3>
        <ul style="margin:0;padding-left:20px;font-size:13px;color:#64748b;">{''.join(daily_lines)}</ul>
        """

    sources = trends.get("top_sources", [])
    sources_html = ""
    if sources:
        parts = [f"{name} ({count})" for name, count in sources[:6]]
        sources_html = f"<p style='margin:12px 0 0;font-size:13px;color:#64748b;'>活跃来源：{'、'.join(parts)}</p>"

    return f"""
  <div style="background:#f0fdf4;border-radius:8px;padding:16px;margin-bottom:20px;">
    <h2 style="margin:0 0 10px;font-size:16px;color:#166534;">📈 7天趋势分析</h2>
    {body}
    {table}
    {daily_html}
    {sources_html}
  </div>
  """


def _render_weekly_article(art: ProcessedArticle) -> str:
    fact = next((f for f in art.facts_zh if f.strip()), art.title_zh)
    titles_html = _render_titles(art.all_titles)
    region_note = f"[{art.region}] " if art.region else ""
    return f"""
    <div style="margin-bottom:14px;padding:10px;border-left:3px solid #16a34a;background:#fafafa;">
      <p style="margin:0 0 4px;font-size:14px;">
        {art.credibility_label} {region_note}<strong>[{art.source}]</strong> {art.title_zh}
      </p>
      <p style="margin:0 0 4px;color:#64748b;font-size:12px;">
        {_format_beijing_time(art.published_at)} (北京时间)
      </p>
      <p style="margin:0 0 4px;font-size:12px;color:#475569;">{titles_html}</p>
      <p style="margin:0;font-size:13px;">{fact}</p>
      <p style="margin:4px 0 0;"><a href="{art.url}" style="color:#2563eb;font-size:12px;">阅读原文</a></p>
    </div>
    """


def _render_weekly_geo_section(items: list[ProcessedArticle], limit: int = 12) -> str:
    by_region: dict[str, list[ProcessedArticle]] = defaultdict(list)
    for art in items:
        by_region[art.region or "其他"].append(art)

    html = ""
    remaining = limit
    for region in GEO_REGION_ORDER:
        if remaining <= 0:
            break
        region_items = by_region.get(region, [])
        if not region_items:
            continue
        region_items.sort(key=lambda a: (len(a.cluster_sources or []), a.source_score), reverse=True)
        picked = region_items[:remaining]
        remaining -= len(picked)
        html += f"""
        <h3 style="color:#334155;margin:12px 0 6px;font-size:14px;">🌏 {region} ({len(picked)}条)</h3>
        {''.join(_render_weekly_article(a) for a in picked)}
        """
    return html


def generate_weekly_html(
    articles: list[ProcessedArticle],
    trends: dict,
    archive_days: int,
    days_covered: list[str],
) -> str:
    now_bj = datetime.now(BEIJING_TZ)
    start_day = (now_bj - timedelta(days=archive_days - 1)).strftime("%Y-%m-%d")
    end_day = now_bj.strftime("%Y-%m-%d")

    top_events = trends.get("top_events", articles[:10])
    grouped: dict[str, list[ProcessedArticle]] = defaultdict(list)
    for art in articles:
        topic = art.topic if art.topic in ("AI", "地缘政治") else "其他"
        grouped[topic].append(art)

    sections = ""
    for topic in ["AI", "地缘政治", "其他"]:
        items = grouped.get(topic, [])
        if not items:
            continue
        items.sort(key=lambda a: (len(a.cluster_sources or []), a.source_score), reverse=True)
        if topic == "地缘政治":
            body = _render_weekly_geo_section(items, limit=12)
        else:
            body = "".join(_render_weekly_article(a) for a in items[:12])
        sections += f"""
        <h2 style="color:#1e293b;border-bottom:2px solid #e2e8f0;padding-bottom:6px;">
          📂 {topic} 精选 ({min(len(items), 12)}条)
        </h2>
        {body}
        """

    trend_html = _render_trend_section(trends)
    archive_note = "、".join(days_covered) if days_covered else "无历史归档，使用实时采集"

    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>新闻周报</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:720px;margin:0 auto;padding:20px;color:#1e293b;">
  <h1 style="color:#0f172a;">📊 新闻深度周报</h1>
  <p style="color:#64748b;">
    {start_day} ~ {end_day} (北京时间)<br>
    生成时间: {now_bj.strftime("%Y-%m-%d %H:%M")}<br>
    本周去重收录 <strong>{len(articles)}</strong> 条 |
    归档天数: {len(days_covered)}/{archive_days} ({archive_note})
  </p>
  {trend_html}
  <hr style="border:none;border-top:1px solid #e2e8f0;">
  <h2 style="color:#1e293b;">🏆 本周 TOP {len(top_events)} 事件</h2>
  {''.join(_render_weekly_article(a) for a in top_events)}
  <hr style="border:none;border-top:1px solid #e2e8f0;">
  {sections or "<p>本周暂无符合条件的新闻。</p>"}
  <hr style="border:none;border-top:1px solid #e2e8f0;">
  <p style="color:#94a3b8;font-size:12px;">
    本报告由每日简报归档自动生成，趋势分析基于规则引擎{(" + Groq" if trends.get("llm_enhanced") else "")}。<br>
    仅供参考，不构成投资建议或政治立场。
  </p>
</body>
</html>"""


def generate_weekly_subject(articles: list[ProcessedArticle], days: int = 7) -> str:
    now_bj = datetime.now(BEIJING_TZ)
    return f"📊 新闻深度周报 | {now_bj.strftime('%Y-%m-%d')} | 近{days}天 {len(articles)}条"
