"""Ghi trace chay that ra logging/trace.jsonl.

README muc 8: trace phai la cua LUOT CHAY MOI NHAT, khong append chong len lan truoc
-> main.py goi reset_trace() mot lan o dau run.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from src import config

_LOCK = threading.Lock()


def reset_trace() -> None:
    """Xoa trace cu. Goi DUNG MOT LAN o dau moi luot chay."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    config.TRACE_PATH.write_text("", encoding="utf-8")


def log_event(
    case_id: str,
    agent: str,
    event: str,
    *,
    payload: Any = None,
    agreement: bool | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Ghi mot dong JSON vao trace.

    agreement=None nghia la buoc nay khong co doi chieu LLM vs deterministic.
    """
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "case_id": case_id,
        "agent": agent,
        "event": event,
    }
    if payload is not None:
        record["payload"] = _shrink(payload)
    if agreement is not None:
        record["agreement"] = agreement
    if latency_ms is not None:
        record["latency_ms"] = round(latency_ms, 1)
    if error is not None:
        record["error"] = error[:500]

    line = json.dumps(record, ensure_ascii=False)
    with _LOCK:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with config.TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _shrink(payload: Any) -> Any:
    """Giu trace gon: cat list dai va chuoi dai, tranh file 100MB."""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if isinstance(payload, dict):
        return {k: _shrink(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_shrink(v) for v in payload[:5]]
    if isinstance(payload, str) and len(payload) > 400:
        return payload[:400] + "..."
    return payload
