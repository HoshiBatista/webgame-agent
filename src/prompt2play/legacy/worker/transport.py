"""Fenced coordinator HTTP operations and renewable lease lifecycle."""

from __future__ import annotations
import threading
import time
from urllib.parse import urlparse
import httpx
from .core import Cancelled, LeaseLost, check_cancel


class CoordinatorUnavailable(RuntimeError):
    """Explicit temporary coordinator overload or server failure."""


class Coordinator:
    def __init__(self, server, token, *, allow_http=False, client=None):
        address = urlparse(server)
        if (
            address.scheme not in ("http", "https")
            or not address.hostname
            or address.username
            or address.password
        ):
            raise ValueError("Coordinator URL must be HTTP(S) without embedded credentials")
        if (
            address.scheme == "http"
            and address.hostname not in ("localhost", "127.0.0.1", "::1")
            and not allow_http
        ):
            raise ValueError(
                "Use HTTPS for remote coordinators; --allow-http is an explicit development-only override"
            )
        self.client = client or httpx.Client(
            base_url=server.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + token},
            timeout=15,
            follow_redirects=False,
        )

    def post(self, path, data, cancel=None):
        if cancel is not None:
            check_cancel(cancel)
        response = self.client.post(path.lstrip("/"), json=data)
        if response.status_code in (401, 403, 409):
            if cancel is not None:
                cancel.set()
            raise LeaseLost(
                f"Coordinator rejected credentials or current lease ({response.status_code})"
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise CoordinatorUnavailable(
                f"Coordinator temporarily unavailable ({response.status_code})"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Coordinator rejected {path.split('/')[-2]} ({response.status_code})"
            )
        return response.json()

    def claim(self, capabilities, name=""):
        payload = {"capabilities": capabilities}
        if name:
            payload["name"] = name
        return self.post("api/worker/claim/", payload)

    def close(self):
        self.client.close()


class Lease:
    def __init__(self, coordinator, claim, cancel):
        self.coordinator, self.cancel = coordinator, cancel
        self.job_id = claim["job"]["id"]
        self.token = claim["lease_token"]
        self.seconds = float(claim.get("lease_seconds", 120))
        self.last_ack = time.monotonic()
        self.stop = threading.Event()
        self.thread = None

    def write(self, action, **payload):
        return self.coordinator.post(
            f"api/worker/jobs/{self.job_id}/{action}/",
            {"lease_token": self.token, **payload},
            self.cancel,
        )

    def __enter__(self):
        self.thread = threading.Thread(target=self._heartbeats, daemon=True)
        self.thread.start()
        return self

    def _heartbeats(self):
        while not self.stop.wait(max(1, min(20, self.seconds / 4))):
            try:
                data = self.write("heartbeat")
                if data.get("cancelled"):
                    self.cancel.set()
                    return
                self.seconds = float(data.get("lease_seconds", 120))
                self.last_ack = time.monotonic()
            except Cancelled:
                self.cancel.set()
                return
            except Exception:
                if time.monotonic() - self.last_ack >= max(1, self.seconds - 20):
                    self.cancel.set()
                    return

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=16)
