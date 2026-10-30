"""Independent HTTP contract peer; cannot contact a model or import worker code."""

import json

import httpx

from generation.relay_api.protocol import digest


class CodexDouble:
    def __init__(self):
        self.jobs, self.calls = {}, []
        self.fail = None
        self.inferences = 0

    def __call__(self, request):
        path = request.url.path.removeprefix("/codex/v1")
        self.calls.append((request.method, path))
        if self.fail:
            return httpx.Response(self.fail, json={"error": "offline"})
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "protocol": 1, "worker_online": True,
                                            "draining": False, "attention_required": False})
        if path == "/models":
            return httpx.Response(200, json={"models": [{"id": "gpt-6-sol", "name": "Sol",
                                                        "efforts": ["low", "medium", "high"]}]})
        parts = path.strip("/").split("/")
        ident = parts[1]
        if request.method == "PUT":
            payload = json.loads(request.content)["payload"]
            self.jobs.setdefault(ident, {"id": ident, "state": "queued", "payload": payload,
                                        "payload_hash": digest(payload), "receipt_hash": None,
                                        "inference_submitted": False})
        if request.method == "POST":
            self.jobs.setdefault(ident, {"id": ident, "state": "queued", "payload_hash": None,
                                        "inference_submitted": False})
            if self.jobs[ident]["state"] not in {"completed", "failed", "unknown", "cancelled"}:
                self.finish(ident, state="cancelled", submitted=self.jobs[ident]["inference_submitted"])
        if ident not in self.jobs:
            return httpx.Response(404, json={"error": "job_not_found"})
        row = {k: v for k, v in self.jobs[ident].items() if k != "payload" and
               (k != "receipt" or parts[-1] == "result")}
        return httpx.Response(200, json=row)

    def finish(self, ident, response=None, *, state="completed", submitted=True, usage=True):
        row = self.jobs[ident]
        if submitted and not row["inference_submitted"]:
            self.inferences += 1
        row.update(state=state, inference_submitted=submitted)
        receipt = {"ok": state == "completed", "usage": {
            "input_tokens": 100, "cached_input_tokens": 10, "cache_write_input_tokens": 0, "output_tokens": 50,
        } if usage and submitted else None, "metadata": {"environment_access": False}}
        if state == "completed":
            receipt.update(model="gpt-6-sol", response=response, raw_response=json.dumps(response))
        else:
            receipt.update(error={"code": "cancelled" if state == "cancelled" else "worker_lost",
                                  "outcome_unknown": submitted}, partial_response="partial" if submitted else None)
        row.update(receipt=receipt, receipt_hash=digest(receipt))
