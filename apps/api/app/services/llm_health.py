"""Whether the configured LLM actually works — recorded from real calls.

Every LLM caller (quote parser, RFQ body generator, sourcing relevance…) falls
back to a deterministic path when the model call fails, which is right for the
user but used to be *silent*: a wrong key or base URL (an OpenAI `sk-proj-`
key paired with the OpenRouter base URL, say) meant every call 401'd and the
app quietly regexed for weeks. Callers now report here; the first failure is
logged at WARNING with a readable reason, Settings shows it via
GET /api/auth/email-config → `llm`, and GET /api/health/providers can probe it.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger("procureai.llm")

_STATE = {"error": None, "at": None, "where": None, "logged": False, "ok_at": None}


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def describe_error(exc: Exception) -> str:
    raw = str(exc) or exc.__class__.__name__
    low = raw.lower()
    if "401" in low or "authentication" in low or "invalid api key" in low or "incorrect api key" in low:
        hint = ""
        base = (settings.openai_base_url or "").lower()
        if "openrouter" in base and settings.openai_api_key.startswith("sk-proj-"):
            hint = (" — an OpenAI sk-proj key is paired with the OpenRouter base URL; use an "
                    "sk-or-… key or clear PROCUREAI_OPENAI_BASE_URL")
        return f"LLM rejected the API key (401){hint}."
    if "429" in low or "rate limit" in low or "quota" in low:
        return "LLM rate limit / quota exceeded (429) — retry later."
    if "404" in low or ("model" in low and "not found" in low):
        return f"LLM model {settings.openai_vision_model!r} not found at the configured base URL."
    if "connection" in low or "timed out" in low or "timeout" in low:
        return "Could not reach the LLM endpoint (network error)."
    return "LLM call failed: " + (raw[:160] + ("…" if len(raw) > 160 else ""))


def record_failure(exc: Exception, where: str) -> str:
    """Note a failed model call. Returns the readable reason."""
    message = describe_error(exc)
    _STATE["error"] = message
    _STATE["at"] = datetime.now(timezone.utc).isoformat()
    _STATE["where"] = where
    if not _STATE["logged"]:
        logger.warning(
            "%s: %s — using the deterministic fallback until the model call recovers.",
            where, message,
        )
        _STATE["logged"] = True
    else:
        logger.info("%s: model call failed again: %s", where, message)
    return message


def record_success() -> None:
    _STATE.update({"error": None, "at": None, "where": None, "logged": False,
                   "ok_at": datetime.now(timezone.utc).isoformat()})


def reset() -> None:
    _STATE.update({"error": None, "at": None, "where": None, "logged": False, "ok_at": None})


def status() -> dict:
    return {
        "configured": is_configured(),
        "model": settings.openai_vision_model,
        "baseUrl": settings.openai_base_url or None,
        "lastError": _STATE["error"],
        "lastErrorAt": _STATE["at"],
        "lastErrorWhere": _STATE["where"],
        "lastOkAt": _STATE["ok_at"],
    }


def probe() -> dict:
    """Actually call the model (one token) and report {ok, error, model}."""
    if not is_configured():
        return {"ok": False, "error": "PROCUREAI_OPENAI_API_KEY is not set", "model": settings.openai_vision_model}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None, timeout=20)
        client.chat.completions.create(
            model=settings.openai_vision_model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=1,
            temperature=0,
        )
    except Exception as exc:
        return {"ok": False, "error": record_failure(exc, "provider probe"), "model": settings.openai_vision_model}
    record_success()
    return {"ok": True, "error": None, "model": settings.openai_vision_model}
