"""Groq LLM client (primary). Falls back to rule engine when unavailable."""

from __future__ import annotations

import logging
import time

from src.config_loader import get_env

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"
_tpd_exhausted = False


def is_available() -> bool:
    return bool(get_env("GROQ_API_KEY")) and not _tpd_exhausted


def _is_tpd_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "tokens per day" in msg or ("rate_limit" in msg and "tpd" in msg)


def generate_text(prompt: str, retries: int = 3) -> str:
    global _tpd_exhausted

    api_key = get_env("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")
    if _tpd_exhausted:
        raise RuntimeError("Groq daily token limit already reached in this run")

    from groq import Groq

    client = Groq(api_key=api_key)
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            content = response.choices[0].message.content
            if content:
                return content
            raise RuntimeError("Empty response from Groq")
        except Exception as exc:
            last_error = exc
            if _is_tpd_limit(exc):
                _tpd_exhausted = True
                logger.warning("Groq daily token limit reached, using rule fallbacks for remainder")
                raise RuntimeError("Groq TPD limit reached") from exc

            msg = str(exc).lower()
            if "429" in msg or "rate" in msg:
                wait = (attempt + 1) * 5
                logger.warning("Groq rate limited, retry in %ds", wait)
                time.sleep(wait)
                continue
            raise

    raise last_error  # type: ignore[misc]
