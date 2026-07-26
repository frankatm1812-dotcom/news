"""Groq LLM client (primary). Falls back to rule engine when unavailable."""

from __future__ import annotations

import logging
import time

from src.config_loader import get_env

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"


def is_available() -> bool:
    return bool(get_env("GROQ_API_KEY"))


def generate_text(prompt: str, retries: int = 3) -> str:
    api_key = get_env("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set")

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
            msg = str(exc).lower()
            if "429" in msg or "rate" in msg:
                wait = (attempt + 1) * 10
                logger.warning("Groq rate limited, retry in %ds", wait)
                time.sleep(wait)
                continue
            raise

    raise last_error  # type: ignore[misc]
