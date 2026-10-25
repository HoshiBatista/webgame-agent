"""Bounded, content-free diagnostics for a single model HTTP request."""

import copy
import logging
import re
import threading
import time
import uuid
from datetime import UTC, datetime

import httpx

logger = logging.getLogger("generation.transport")


def utc_now():
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def safe_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value) else None


def error_facts(exc):
    """Never log exception text: it can embed headers, URLs, or response content."""
    chain: list[dict] = []
    seen = set()
    current = exc
    while current is not None and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        item = {"type": type(current).__name__}
        if isinstance(getattr(current, "errno", None), int):
            item["errno"] = current.errno
        chain.append(item)
        current = current.__cause__ or current.__context__
    return chain


class TransportDiagnostics:
    def __init__(self, *, trace_id, config, request_bytes, streaming):
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.last_byte = None
        self.last_report = self.started
        self.finished = False
        self.data = {
            "trace_id": uuid.UUID(str(trace_id)).hex if trace_id else uuid.uuid4().hex,
            "started_at": utc_now(), "phase": "created", "streaming": streaming,
            "request_bytes": request_bytes, "received_bytes": 0, "received_chunks": 0,
            "sse_events": 0, "output_bytes": 0, "done_received": False,
            "max_byte_gap_seconds": 0.0,
            "timeouts": {"connect": config["connect_timeout"], "read": config["read_timeout"],
                         "write": 30, "pool": 10},
            "http_events": [],
        }

    def update(self, **values):
        with self.lock:
            if not self.finished:
                self.data.update(values)

    def received(self, chunk):
        now = time.monotonic()
        with self.lock:
            if self.finished:
                return
            if self.last_byte is None:
                self.data["first_byte_seconds"] = round(now - self.started, 3)
            else:
                self.data["max_byte_gap_seconds"] = round(
                    max(self.data["max_byte_gap_seconds"], now - self.last_byte), 3
                )
            self.last_byte = now
            self.data["last_byte_at"] = utc_now()
            self.data["received_bytes"] += len(chunk)
            self.data["received_chunks"] += 1

    def sse_event(self):
        with self.lock:
            if not self.finished:
                self.data["sse_events"] += 1

    def trace(self, name, info):
        # HTTPX/httpcore trace metadata includes raw headers; retain only event names/times.
        if not re.fullmatch(r"[a-z0-9_.]{1,100}", name):
            return
        item = {"event": name, "seconds": round(time.monotonic() - self.started, 3)}
        if isinstance(info.get("exception"), Exception):
            item["errors"] = error_facts(info["exception"])
        with self.lock:
            if self.finished:
                return
            self.data["http_events"].append(item)
            self.data["http_events"] = self.data["http_events"][-32:]

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.data)
            if not self.finished:
                now = time.monotonic()
                result["elapsed_seconds"] = round(now - self.started, 3)
                result["idle_seconds"] = round(now - (self.last_byte or self.started), 3)
            return result

    def report(self, event, *, force=False):
        now = time.monotonic()
        if not force and now - self.last_report < 10:
            return
        self.last_report = now
        logger.info("llm_transport", extra={"transport_event": event, "transport": self.snapshot()})

    def finish(self, outcome):
        snapshot = self.snapshot()
        with self.lock:
            self.data.update(elapsed_seconds=snapshot["elapsed_seconds"],
                             idle_seconds=snapshot["idle_seconds"], finished_at=utc_now(), outcome=outcome)
            self.finished = True
        self.report("finished", force=True)
        return self.snapshot()


class ObservedStream(httpx.SyncByteStream):
    def __init__(self, stream, diagnostics):
        self.stream = stream
        self.diagnostics = diagnostics

    def __iter__(self):
        for chunk in self.stream:
            self.diagnostics.received(chunk)
            yield chunk

    def close(self):
        self.stream.close()


class TransportLogFormatter(logging.Formatter):
    def format(self, record):
        import json

        # Explicit allowlist: do not serialize LogRecord args or arbitrary exception text.
        return json.dumps({"ts": utc_now(), "event": record.transport_event,
                           "transport": record.transport}, ensure_ascii=True)
