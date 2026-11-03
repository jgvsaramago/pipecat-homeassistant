"""Token usage and transcripts of satellite conversations (ByteHomeDash fork).

A realtime model reports its usage at the end of every model turn (Gemini
Live: ``usage_metadata``, the whole context counted again each turn). Each
turn becomes one JSON line in ``/data/usage/YYYY-MM.jsonl`` with the tokens
by kind and the last thing said on each side, grouped into conversations by
the satellite's wake counter. ``summary()`` aggregates them for
``GET /api/assist/usage``.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import DATA_DIR

USAGE_DIR = DATA_DIR / "usage"
_LOCK = threading.Lock()
_TEXT_LIMIT = 2000
_KEEP_MONTHS = 12


def _modalities(details: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in details or []:
        modality = getattr(item, "modality", None)
        name = str(getattr(modality, "value", modality) or "other").lower()
        out[name] = out.get(name, 0) + int(getattr(item, "token_count", 0) or 0)
    return out


class SessionUsage:
    """One satellite connection (one model session at a time)."""

    def __init__(self, *, session_id: str, client_id: str, flow_id: str, model: str) -> None:
        self.session_id = session_id
        self.client_id = client_id
        self.flow_id = flow_id
        self.model = model
        self.conversation = 0
        self._user = ""
        self._assistant = ""
        self._turn = 0

    def on_conversation(self, number: int) -> None:
        self.conversation = number

    def on_text(self, role: str, text: str) -> None:
        text = text.strip()[:_TEXT_LIMIT]
        if not text:
            return
        if role == "user":
            self._user = text
        else:
            self._assistant = text

    def on_usage(self, usage: Any) -> None:
        if usage is None:
            return
        self._turn += 1
        record = {
            "ts": round(time.time(), 3),
            "session": self.session_id,
            "client": self.client_id,
            "flow": self.flow_id,
            "model": self.model,
            "conversation": self.conversation,
            "turn": self._turn,
            "prompt": int(usage.prompt_token_count or 0),
            "cached": int(usage.cached_content_token_count or 0),
            "response": int(usage.response_token_count or 0),
            "tool_prompt": int(usage.tool_use_prompt_token_count or 0),
            "thoughts": int(usage.thoughts_token_count or 0),
            "total": int(usage.total_token_count or 0),
            "prompt_by": _modalities(usage.prompt_tokens_details),
            "response_by": _modalities(usage.response_tokens_details),
            "cached_by": _modalities(usage.cache_tokens_details),
            "user": self._user,
            "assistant": self._assistant,
        }
        self._user = ""
        self._assistant = ""
        _append(record)


def _append(record: dict[str, Any]) -> None:
    try:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        path = USAGE_DIR / f"{datetime.now():%Y-%m}.jsonl"
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _prune()
    except Exception as err:  # never break a conversation over logging
        logger.warning("Usage log: {}", err)


def _prune() -> None:
    files = sorted(USAGE_DIR.glob("*.jsonl"))
    for old in files[:-_KEEP_MONTHS]:
        old.unlink(missing_ok=True)


def _records(since: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not USAGE_DIR.exists():
        return out
    first = datetime.fromtimestamp(since).strftime("%Y-%m")
    for path in sorted(USAGE_DIR.glob("*.jsonl")):
        if path.stem < first:
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("ts", 0) >= since:
                    out.append(record)
    return out


def _tokens(records: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("prompt", "cached", "response", "tool_prompt", "thoughts", "total")
    sums = {k: sum(int(r.get(k) or 0) for r in records) for k in keys}
    for side in ("prompt_by", "response_by"):
        for record in records:
            for modality, count in (record.get(side) or {}).items():
                key = f"{side[:-3]}_{modality}"
                sums[key] = sums.get(key, 0) + int(count or 0)
    sums["turns"] = len(records)
    return sums


def summary(days: int = 30, conversations: int = 50) -> dict[str, Any]:
    """Totals per day and the latest conversations with their turns."""
    days = max(1, min(int(days), 366))
    since = (datetime.now() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    records = _records(since)
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_conversation: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_day[datetime.fromtimestamp(record["ts"]).strftime("%Y-%m-%d")].append(record)
        by_conversation[(record.get("session", ""), int(record.get("conversation") or 0))].append(record)
    convs = []
    for (session, number), turns in by_conversation.items():
        turns.sort(key=lambda r: r["ts"])
        convs.append(
            {
                "session": session,
                "conversation": number,
                "client": turns[0].get("client"),
                "model": turns[0].get("model"),
                "start": turns[0]["ts"],
                "end": turns[-1]["ts"],
                "tokens": _tokens(turns),
                "turns": [
                    {k: t.get(k) for k in ("ts", "prompt", "cached", "response", "tool_prompt", "thoughts", "total", "prompt_by", "response_by", "user", "assistant")}
                    for t in turns
                ],
            }
        )
    convs.sort(key=lambda c: c["start"], reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "days": days,
        "totals": {**_tokens(records), "conversations": len(by_conversation)},
        "today": {**_tokens(by_day.get(today, [])), "conversations": len({(r.get("session"), r.get("conversation")) for r in by_day.get(today, [])})},
        "by_day": [
            {"day": day, **_tokens(rows), "conversations": len({(r.get("session"), r.get("conversation")) for r in rows})}
            for day, rows in sorted(by_day.items())
        ],
        "conversations": convs[: max(0, int(conversations))],
    }


_CONTEXT_PATH = USAGE_DIR / "context.json"


def save_context(context: dict[str, Any]) -> None:
    """The context a new model session was opened with (instructions, the
    integration's prompt, tools), kept for `GET /api/assist/context`."""
    try:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            _CONTEXT_PATH.write_text(json.dumps(context, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as err:
        logger.warning("Usage log: context: {}", err)


def last_context() -> dict[str, Any] | None:
    try:
        return json.loads(_CONTEXT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
