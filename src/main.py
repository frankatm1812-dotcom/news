"""News briefing pipeline entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.collectors import collect_all
from src.filters.time_filter import filter_last_12_hours
from src.output.briefing import generate_html, generate_subject
from src.output.email_sender import send_email
from src.processors.credibility import assign_credibility
from src.processors.deduplicator import deduplicate
from src.processors.extractor import extract_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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

    max_articles = limit or 35
    if len(filtered) > max_articles:
        filtered = sorted(filtered, key=lambda a: a.published_at, reverse=True)[:max_articles]
        logger.info("Capped to %d most recent articles", max_articles)

    processed = extract_all(filtered)
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
    parser.add_argument("--limit", type=int, default=None, help="Max articles to process (default 35)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
