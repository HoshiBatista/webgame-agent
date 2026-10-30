"""Test double for protocol v1; no imports from either server or GameForge."""

import json

from generation.relay_api.protocol import digest, encoded


def failure(code, message, *, unknown=True):
    return {"ok": False, "error": {"code": code, "message": message, "outcome_unknown": unknown}}


class RelayDouble:
    def __init__(self):
        self.jobs = {}
        self.tokens = {"alice": "client", "gpu": "worker", "gpu2": "worker"}
        self.path = None

    def get(self, ident, owner):
        return self.jobs[ident]

    def claim(self, worker):
        for row in self.jobs.values():
            if row.get("receipt"):
                continue
            if row.get("worker") not in {None, worker}:
                return None
            row["worker"] = worker
            if row["state"] == "queued":
                row["state"] = "assigned"
            return row.copy()

    def worker_update(self, ident, worker, *, start=False):
        row = self.jobs[ident]
        if start:
            row["state"] = "running"
        return row

    def finish(self, ident, worker, receipt):
        row = self.jobs[ident]
        checksum = digest(receipt)
        if row.get("receipt_hash") and row["receipt_hash"] != checksum:
            return {"error": "conflict"}
        row.update(
            receipt=receipt,
            receipt_hash=checksum,
            state="completed"
            if receipt["ok"]
            else ("unknown" if receipt["error"]["outcome_unknown"] else "failed"),
        )
        return {"receipt_hash": checksum}

    def __call__(self, environ, start_response):
        actor = environ.get("HTTP_AUTHORIZATION", "")[7:]
        path = environ["PATH_INFO"].removeprefix("/bridge/v1")
        method = environ["REQUEST_METHOD"]
        size = int(environ.get("CONTENT_LENGTH") or 0)
        body = json.loads(environ["wsgi.input"].read(size)) if size else {}
        status = 200
        if path == "/worker/claim":
            value = {"job": self.claim(actor)}
        else:
            ident = path.split("/")[2]
            if path.startswith("/jobs/"):
                if method == "PUT":
                    self.jobs.setdefault(
                        ident,
                        {
                            "id": ident,
                            "payload": body["payload"],
                            "state": "queued",
                            "cancel_requested": False,
                        },
                    )
                if ident not in self.jobs:
                    value = {"error": "not_found"}
                    status = 404
                else:
                    value = self.jobs[ident]
                    if path.endswith("/cancel"):
                        value["cancel_requested"] = True
                        if value["state"] == "queued":
                            receipt = failure("cancelled", "Cancelled", unknown=False)
                            value.update(state="cancelled", receipt=receipt, receipt_hash=digest(receipt))
            elif path.endswith("/receipt"):
                value = self.finish(ident, actor, body)
                if "error" in value:
                    status = 409
            else:
                value = self.worker_update(ident, actor, start=path.endswith("/start"))
        data = encoded(value).encode()
        start_response(
            f"{status} Test", [("Content-Type", "application/json"), ("Content-Length", str(len(data)))]
        )
        return [data]
