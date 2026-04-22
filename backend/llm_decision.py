"""LLM-backed claim decision via Groq; structured JSON validated against SimulateResponse."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from schemas import SimulateResponse
from settings import Settings


_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "decision.txt"


def _load_instruction() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", t)
    if m:
        return m.group(1).strip()
    if t.startswith("```"):
        t = re.sub(r"^```[^\n]*\n", "", t)
        t = re.sub(r"\n```$", "", t)
    return t.strip()


def _first_json_object(text: str) -> str:
    """If the model wraps JSON in prose or multiple objects, pull the first valid top-level object."""
    t = _strip_json_fence(text).strip()
    if not t:
        return ""
    try:
        json.loads(t)
        return t
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch != "{":
            continue
        try:
            _, end = dec.raw_decode(t[i:])
            return t[i : i + end]
        except json.JSONDecodeError:
            continue
    return t


def _assistant_text_from_response(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Groq response has no choices.")
    choice = choices[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if content is not None and str(content).strip():
        return str(content)
    # Some APIs expose only tool calls or alternate fields
    fr = choice.get("finish_reason")
    extra = f" finish_reason={fr!r} message_keys={list(msg.keys())}"
    raise RuntimeError(
        "Groq returned empty assistant text."
        + extra
        + " Try increasing max_tokens, another model, or check Groq status."
    )


def _call_groq(document_excerpt: str, settings: Settings) -> str:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to backend/.env.")

    system = _load_instruction()
    user = f"Document excerpt (may be truncated):\n\n{document_excerpt}"

    payload: dict = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
        # Ask for a JSON object only (when the model + Groq support it)
        "response_format": {"type": "json_object"},
    }

    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )

    # Some models reject json_object mode; retry once without it
    if r.status_code == 400:
        try:
            err = r.json()
            msg = str(err.get("error", err)).lower()
        except Exception:
            msg = r.text[:500] if r.text else ""
        if "json" in msg or "response_format" in msg or "unsupported" in msg:
            r = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.groq_model,
                    "messages": payload["messages"],
                    "temperature": payload["temperature"],
                    "max_tokens": payload["max_tokens"],
                },
                timeout=settings.llm_timeout_seconds,
            )

    r.raise_for_status()
    data = r.json()
    return _assistant_text_from_response(data)


def decide_from_document_text(document_text: str, settings: Settings) -> SimulateResponse:
    max_c = settings.document_text_max_chars
    excerpt = document_text if len(document_text) <= max_c else document_text[:max_c] + "\n\n[TRUNCATED]"

    try:
        raw = _call_groq(excerpt, settings)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Groq request failed: {e}") from e

    cleaned = _first_json_object(raw)
    if not cleaned.strip():
        preview = (raw or "")[:400].replace("\n", " ")
        raise ValueError(
            f"LLM returned unusable output (empty after parse). Preview: {preview!r}"
        )

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError as e:
        preview = cleaned[:500] if cleaned else "(empty)"
        raise ValueError(
            f"LLM returned invalid JSON: {e}. First 500 chars: {preview!r}"
        ) from e

    return SimulateResponse.model_validate(obj)


def llm_backend_ready(settings: Settings) -> tuple[bool, str | None]:
    """Quick check that Groq API key is present (not a full generation test)."""
    if settings.groq_api_key and settings.groq_api_key.strip():
        return True, None
    return False, "GROQ_API_KEY missing or empty in environment / backend/.env"
