"""Content-free JSON events. Only explicit numeric/enum/UUID fields are emitted."""

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def emit(event, **facts):
    logger.info(json.dumps({"event": event, "at": datetime.now(UTC).isoformat(), **facts},
                           separators=(",", ":")), extra={"transport_event": event, "transport": facts})


def errors(exc):
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen and len(result) < 6:
        seen.add(id(exc))
        item = {"type": type(exc).__name__}
        if isinstance(getattr(exc, "errno", None), int):
            item["errno"] = exc.errno
        result.append(item)
        exc = exc.__cause__ or exc.__context__
    return result


class Meter(httpx.SyncByteStream):
    def __init__(self, stream, facts, started):
        self.stream, self.facts, self.started = stream, facts, started
        self.last = None

    def __iter__(self):
        for chunk in self.stream:
            now = time.monotonic()
            self.facts["received_bytes"] += len(chunk)
            if self.last is None:
                self.facts["first_byte_seconds"] = round(now - self.started, 3)
            else:
                self.facts["max_byte_gap_seconds"] = max(
                    self.facts.get("max_byte_gap_seconds", 0), round(now - self.last, 3))
            self.last = now
            yield chunk

    def close(self):
        self.stream.close()
