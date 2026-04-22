"""LLM-backed claim decision via Groq; structured JSON validated against SimulateResponse."""

from __future__ import annotations

import json
import re
from json import dumps as _json_dumps
from pathlib import Path

import httpx

from schemas import SimulateResponse
from settings import Settings


_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_PROMPT_FULL = _PROMPT_DIR / "decision.txt"
_PROMPT_COMPACT = _PROMPT_DIR / "decision_compact.txt"


def _load_instruction(settings: Settings) -> str:
    path = _PROMPT_COMPACT if settings.groq_compact_system_prompt else _PROMPT_FULL
    return path.read_text(encoding="utf-8").strip()


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


def _json_body_size(payload: dict) -> int:
    """Byte length of JSON exactly as httpx serializes it (see httpx._content.encode_json)."""
    return len(
        _json_dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    )


def _shrink_excerpt_for_groq_limit(
    document_excerpt: str,
    system: str,
    settings: Settings,
    max_body_bytes: int | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict]:
    """
    Groq rejects oversized bodies with HTTP 413. Shrink the user message until the
    serialized request fits under the byte budget.
    """
    prefix = "Document excerpt (may be truncated):\n\n"
    excerpt = document_excerpt
    limit = settings.groq_max_request_body_bytes if max_body_bytes is None else max_body_bytes
    completion_cap = settings.groq_max_tokens if max_tokens is None else max_tokens

    def payload_for(ex: str, with_json_mode: bool) -> dict:
        user = prefix + ex
        p: dict = {
            "model": settings.groq_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": completion_cap,
        }
        if with_json_mode:
            p["response_format"] = {"type": "json_object"}
        return p

    def fits(p: dict) -> bool:
        return _json_body_size(p) <= limit

    with_json = True
    payload = payload_for(excerpt, with_json)
    while excerpt and not fits(payload):
        cut = max(400, len(excerpt) // 8)
        excerpt = excerpt[:-cut]
        suffix = "\n\n[TRUNCATED for API size limit]" if excerpt != document_excerpt else ""
        payload = payload_for(excerpt + suffix, with_json)

    if not excerpt:
        payload = payload_for("[no excerpt could be fit under API size limit]", with_json)

    return excerpt, payload


def _groq_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
    except Exception:
        pass
    return (response.text or "").strip()[:800]


def _call_groq(document_excerpt: str, settings: Settings) -> str:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to backend/.env.")

    system = _load_instruction(settings)
    body_limit = settings.groq_max_request_body_bytes
    completion_cap = settings.groq_max_tokens
    r: httpx.Response | None = None

    for _attempt in range(14):
        _excerpt, payload = _shrink_excerpt_for_groq_limit(
            document_excerpt,
            system,
            settings,
            max_body_bytes=body_limit,
            max_tokens=completion_cap,
        )
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.llm_timeout_seconds,
        )
        if r.status_code != 413:
            break
        # Groq often uses 413 for per-request token / TPM limits; shrink inputs and completion budget.
        body_limit = max(6_000, int(body_limit * 0.55))
        completion_cap = max(512, int(completion_cap * 0.65))

    assert r is not None
    if r.status_code == 413:
        detail = _groq_error_message(r)
        raise RuntimeError(
            "Groq returned HTTP 413. This is often a token / tier limit (not file upload size). "
            f"Groq said: {detail} "
            "Try: lower GROQ_MAX_DOCUMENT_CHARS (e.g. 8000), set GROQ_MAX_TOKENS=2048, "
            "ensure GROQ_COMPACT_SYSTEM_PROMPT=true, or upgrade your Groq plan."
        )

    # Some models reject json_object mode; retry once without it
    if r.status_code == 400:
        try:
            err = r.json()
            msg = str(err.get("error", err)).lower()
        except Exception:
            msg = r.text[:500] if r.text else ""
        if "json" in msg or "response_format" in msg or "unsupported" in msg:
            payload.pop("response_format", None)
            r = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=settings.llm_timeout_seconds,
            )

    r.raise_for_status()
    data = r.json()
    return _assistant_text_from_response(data)


def decide_from_document_text(document_text: str, settings: Settings) -> SimulateResponse:
    max_c = min(settings.document_text_max_chars, settings.groq_max_document_chars)
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
