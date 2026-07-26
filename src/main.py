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
from src.filters.time_filter import filter_last_12_hours
from src.output.briefing import generate_html, generate_subject
from src.output.email_sender import send_email, send_failure_notification
from src.processors.credibility import assign_credibility
from src.processors.deduplicator import deduplicate
from src.processors.extractor import extract_all
from src.processors.rule_engine import pre_deduplicate_raw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _max_articles(limit: int | None) -> int:
    if limit is not None:
        return limit
    cfg = load_yaml("settings.yaml")
    return cfg.get("processing", {}).get("max_articles", 35)


def run(dry_run: bool = False, limit: int | None = None) -> None:
    logger.info("Starting news briefing pipeline")

    raw_articles = collect_all()
    raw_count = len(raw_articles)

    filtered = filter_last_12_hours(raw_articles)
    filtered_count = len(filtered)

    if not filtered:
        logger.warning("No articles in 12h window")
        html = generate_html([], raw_count, 0)
        subject = generate_subject([])
        if dry_run:
            out = ROOT / "briefing_preview.html"
            out.write_text(html, encoding="utf-8")
            logger.info("Dry run: wrote %s", out)
            return
        send_email(subject, html)
        return

    # Pre-dedup before LLM to reduce API calls
    pre_deduped = pre_deduplicate_raw(filtered)
    logger.info("After pre-dedup: %d -> %d", len(filtered), len(pre_deduped))

    cap = _max_articles(limit)
    if len(pre_deduped) > cap:
        pre_deduped = sorted(pre_deduped, key=lambda a: a.published_at, reverse=True)[:cap]
        logger.info("Capped to %d most recent articles", cap)

    processed = extract_all(pre_deduped)
    deduped = deduplicate(processed)
    final = assign_credibility(deduped)

    html = generate_html(final, raw_count, filtered_count)
    subject = generate_subject(final)

    if dry_run:
        out = ROOT / "briefing_preview.html"
        out.write_text(html, encoding="utf-8")
        logger.info("Dry run: wrote %s (%d articles)", out, len(final))
        return

    send_email(subject, html)
    logger.info("Pipeline complete: %d articles delivered", len(final))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and send news briefing")
    parser.add_argument("--dry-run", action="store_true", help="Skip email, write preview HTML")
    parser.add_argument("--limit", type=int, default=None, help="Max articles to process (default from settings)")
    args = parser.parse_args()

    try:
        run(dry_run=args.dry_run, limit=args.limit)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        if not args.dry_run:
            send_failure_notification(str(exc), traceback.format_exc())
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
