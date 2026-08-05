"""Wrapper Groq dung chung cho moi agent.

Nguyen tac (docs/TEAM_PLAN.md muc 1):
  - LLM chi SUY LUAN va RA QUYET DINH, khong bao gio la nguon cua con so hay ID.
  - Moi ket qua LLM deu phai di qua mot guard deterministic o phia agent goi no.
  - Khong co API key -> call_json() tra None, agent tu dong chay deterministic-only.
    Nho vay pipeline luon chay duoc, ke ca khi Groq rate-limit hay mat mang.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from src import config
from src.trace import log_event

_CLIENT = None
_CLIENT_FAILED = False


def _client():
    global _CLIENT, _CLIENT_FAILED
    if _CLIENT is not None or _CLIENT_FAILED:
        return _CLIENT
    key = config.api_key()
    if not key:
        _CLIENT_FAILED = True
        return None
    try:
        from groq import Groq

        _CLIENT = Groq(api_key=key, timeout=config.LLM_TIMEOUT_S)
    except Exception:
        _CLIENT_FAILED = True
        _CLIENT = None
    return _CLIENT


def call_json(
    *,
    case_id: str,
    agent: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any] | None:
    """Goi model, ep tra ve mot JSON object.

    Tra None khi: khong co key, het retry, hoac khong parse duoc JSON.
    Caller PHAI xu ly duoc truong hop None.
    """
    client = _client()
    if client is None:
        log_event(case_id, agent, "llm_skipped", payload={"reason": "no_api_key"})
        return None

    last_err = ""
    for attempt in range(1, config.LLM_MAX_RETRIES + 1):
        started = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=config.LLM_MODEL,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            latency = (time.perf_counter() - started) * 1000
            raw = resp.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if parsed is None:
                last_err = f"unparsable json: {raw[:200]}"
                continue
            log_event(
                case_id,
                agent,
                "llm_call",
                payload={"model": config.LLM_MODEL, "attempt": attempt, "out": parsed},
                latency_ms=latency,
            )
            return parsed
        except Exception as exc:  # rate limit, timeout, network...
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** attempt * 0.5, 4.0))

    log_event(case_id, agent, "llm_failed", error=last_err)
    return None


def _parse_json(raw: str) -> dict[str, Any] | None:
    """Parse JSON, co vot truong hop model bo them ```json fence hoac chu thua."""
    raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass
    return None
