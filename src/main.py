"""News briefing pipeline entry point."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collectors import collect_all
from src.config_loader import load_yaml
from src.models import ProcessedArticle
from src.filters.time_filter import filter_last_12_hours, filter_last_n_days
from src.filters.time_sampler import cap_articles
from src.output.briefing import generate_html, generate_subject
from src.output.email_sender import send_email, send_failure_notification
from src.output.highlights import generate_highlights
from src.output.weekly_briefing import generate_weekly_html, generate_weekly_subject
from src.processors.credibility import assign_credibility
from src.processors.deduplicator import deduplicate
from src.processors.extractor import extract_all
from src.processors.geo_region import assign_geo_regions
from src.processors.rule_engine import pre_deduplicate_raw
from src.processors.trends import analyze_trends
from src.storage.archive import (
    flatten_archives,
    load_archives_last_n_days,
    save_daily_archive,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _max_articles(limit: int | None, weekly: bool = False) -> int:
    if limit is not None:
        return limit
    cfg = load_yaml("settings.yaml")
    if weekly:
        return cfg.get("weekly", {}).get("max_articles", 50)
    return cfg.get("processing", {}).get("max_articles", 35)


def _process_raw(pre_deduped: list, limit: int | None) -> list:
    cap = _max_articles(limit)
    if len(pre_deduped) > cap:
        pre_deduped = cap_articles(pre_deduped, cap)

    processed = extract_all(pre_deduped)
    deduped = deduplicate(processed)
    return assign_geo_regions(assign_credibility(deduped))


def run(dry_run: bool = False, limit: int | None = None, skip_archive: bool = False) -> None:
    logger.info("Starting news briefing pipeline")

    raw_articles = collect_all()
    raw_count = len(raw_articles)

    filtered = filter_last_12_hours(raw_articles)
    filtered_count = len(filtered)

    if not filtered:
        logger.warning("No articles in 12h window")
        html = generate_html([], raw_count, 0, highlights="过去12小时内未找到符合条件的新闻。")
        subject = generate_subject([])
        if dry_run:
            out = ROOT / "briefing_preview.html"
            out.write_text(html, encoding="utf-8")
            logger.info("Dry run: wrote %s", out)
            return
        send_email(subject, html)
        return

    pre_deduped = pre_deduplicate_raw(filtered)
    logger.info("After pre-dedup: %d -> %d", len(filtered), len(pre_deduped))

    final = _process_raw(pre_deduped, limit)
    highlights = generate_highlights(final)

    if not skip_archive:
        save_daily_archive(final)

    html = generate_html(final, raw_count, filtered_count, highlights=highlights)
    subject = generate_subject(final)

    if dry_run:
        out = ROOT / "briefing_preview.html"
        out.write_text(html, encoding="utf-8")
        logger.info("Dry run: wrote %s (%d articles)", out, len(final))
        return

    send_email(subject, html)
    logger.info("Pipeline complete: %d articles delivered", len(final))


def run_weekly(dry_run: bool = False, limit: int | None = None) -> None:
    logger.info("Starting weekly deep report pipeline")

    cfg = load_yaml("settings.yaml").get("weekly", {})
    days = cfg.get("archive_days", 7)
    min_from_archive = cfg.get("min_articles_from_archive", 10)

    by_day = load_archives_last_n_days(days)
    archived = flatten_archives(by_day)
    logger.info("Loaded %d articles from %d archive days", len(archived), len(by_day))

    final = archived
    if len(archived) < min_from_archive:
        logger.info("Archive sparse (%d < %d), supplementing with live 7-day collection", len(archived), min_from_archive)
        raw = collect_all()
        filtered = filter_last_n_days(raw, days)
        pre_deduped = pre_deduplicate_raw(filtered)
        live_final = _process_raw(pre_deduped, limit or _max_articles(None, weekly=True))

        merged: dict[str, ProcessedArticle] = {}
        for art in archived + live_final:
            key = art.url.split("?")[0].rstrip("/")
            if key not in merged:
                merged[key] = art
        final = sorted(merged.values(), key=lambda a: a.published_at, reverse=True)

    if not final:
        html = generate_weekly_html([], analyze_trends([], days=days), days, list(by_day.keys()))
        subject = generate_weekly_subject([], days=days)
        if dry_run:
            out = ROOT / "weekly_preview.html"
            out.write_text(html, encoding="utf-8")
            logger.info("Dry run: wrote %s (empty weekly)", out)
            return
        send_email(subject, html)
        return

    trends = analyze_trends(final, days=days)
    final = assign_geo_regions(final)
    html = generate_weekly_html(final, trends, days, list(by_day.keys()))
    subject = generate_weekly_subject(final, days=days)

    if dry_run:
        out = ROOT / "weekly_preview.html"
        out.write_text(html, encoding="utf-8")
        logger.info("Dry run: wrote %s (%d articles)", out, len(final))
        return

    send_email(subject, html)
    logger.info("Weekly report complete: %d articles", len(final))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and send news briefing")
    parser.add_argument("--dry-run", action="store_true", help="Skip email, write preview HTML")
    parser.add_argument("--limit", type=int, default=None, help="Max articles to process")
    parser.add_argument("--weekly", action="store_true", help="Generate weekly deep report instead of daily briefing")
    parser.add_argument("--skip-archive", action="store_true", help="Do not write daily archive (daily mode only)")
    args = parser.parse_args()

    try:
        if args.weekly:
            run_weekly(dry_run=args.dry_run, limit=args.limit)
        else:
            run(dry_run=args.dry_run, limit=args.limit, skip_archive=args.skip_archive)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        if not args.dry_run:
            send_failure_notification(str(exc), traceback.format_exc())
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
