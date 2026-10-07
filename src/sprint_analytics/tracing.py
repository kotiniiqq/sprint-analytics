"""Observability: every LLM call and MCP tool call leaves a trace.

Always: one JSON line per event in `.traces/YYYY-MM-DD.jsonl` (or SA_TRACE_DIR).
Optionally: the same event in Langfuse when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
are set (public ingestion API). Tracing must never break the work it observes,
so every failure here is swallowed and reported on stderr.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

_http: httpx.Client | None = None


def set_http_client(client: httpx.Client | None) -> None:
    """Tests inject a client with a mock transport."""
    global _http
    _http = client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_local(event: dict) -> None:
    folder = Path(os.environ.get("SA_TRACE_DIR", ".traces"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{event['timestamp'][:10]}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def _send_langfuse(event: dict) -> None:
    public, secret = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        return
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    trace_id = event["id"]
    batch = [{
        "id": str(uuid.uuid4()), "timestamp": event["timestamp"], "type": "trace-create",
        "body": {"id": trace_id, "name": event["name"], "input": event.get("input"),
                 "output": event.get("output"), "metadata": event.get("metadata")},
    }]
    if event.get("model"):
        batch.append({
            "id": str(uuid.uuid4()), "timestamp": event["timestamp"], "type": "generation-create",
            "body": {"id": str(uuid.uuid4()), "traceId": trace_id, "name": event["name"],
                     "model": event["model"], "input": event.get("input"), "output": event.get("output"),
                     "usage": {"input": event.get("prompt_tokens"), "output": event.get("completion_tokens"),
                               "totalCost": event.get("cost_usd")},
                     "metadata": {"latency_ms": event.get("latency_ms")}},
        })
    client = _http or httpx.Client(timeout=10)
    response = client.post(f"{host}/api/public/ingestion", json={"batch": batch}, auth=(public, secret))
    if response.status_code >= 400:
        raise RuntimeError(f"Langfuse ingestion returned {response.status_code}")


def trace(name: str, **fields) -> dict:
    """Record one event. Returns the event so callers can attach its id to output."""
    event = {"id": str(uuid.uuid4()), "timestamp": _now(), "name": name, **fields}
    for sink in (_write_local, _send_langfuse):
        try:
            sink(event)
        except Exception as exc:  # noqa: BLE001 - observability must not take the app down
            print(f"[tracing] {sink.__name__} failed: {exc}", file=sys.stderr)
    return event
