"""Structured logging for all LLM (Gemini) invocations.

Logs prompt, response, latency, model, and caller info as JSON to stdout.
Accessible via Render's log viewer for debugging.
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger("llm")


def log_llm_call(
    *,
    caller: str,
    model: str,
    prompt: str,
    response_text: Optional[str] = None,
    latency_ms: float = 0,
    streaming: bool = False,
    error: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Log a single LLM invocation as structured JSON."""
    record = {
        "type": "llm_call",
        "caller": caller,
        "model": model,
        "prompt_length": len(prompt),
        "prompt_preview": prompt[:300],
        "response_length": len(response_text) if response_text else 0,
        "response_preview": response_text[:300] if response_text else None,
        "latency_ms": round(latency_ms, 1),
        "streaming": streaming,
    }
    if error:
        record["error"] = error
    if extra:
        record.update(extra)

    logger.info(json.dumps(record, ensure_ascii=False))


class LLMTimer:
    """Context manager to measure LLM call latency."""

    def __init__(self):
        self.start_time = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.monotonic() - self.start_time) * 1000
