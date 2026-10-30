"""Exercise real Celery delivery without a paid model or private game changes."""

import json
import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
client = httpx.Client(base_url="http://127.0.0.1:8080", timeout=15, trust_env=False)
csrf = client.get("/api/session/").json()["csrfToken"]
login = client.post(
    "/api/login/",
    json={
        "username": os.environ["DJANGO_SUPERUSER_USERNAME"],
        "password": os.environ["DJANGO_SUPERUSER_PASSWORD"],
    },
    headers={"X-CSRFToken": csrf},
)
login.raise_for_status()
session = login.json()
assert session["capabilities"]["provider"] == "fake", "Only the free fixture profile is permitted"
client.headers["X-CSRFToken"] = session["csrfToken"]


def api(method, path, data=None):
    response = client.request(method, path, json=data)
    response.raise_for_status()
    return response.json() if response.content else None


def submit():
    chat = api("POST", "/api/chats/", {"title": "Queue acceptance fixture"})
    run = api(
        "POST",
        f"/api/chats/{chat['id']}/runs/",
        {"prompt": "Queue fixture", "idempotency_key": str(uuid.uuid4())},
    )
    return chat["id"], run["id"]


def await_batch(items):
    deadline = time.monotonic() + 90
    while True:
        results = [api("GET", f"/api/runs/{run}/") for _, run in items]
        if all(r["status"] not in {"queued", "generating", "checking"} for r in results):
            break
        assert time.monotonic() < deadline, "Fixture batch did not finish in test watchdog"
        time.sleep(0.2)
    for (chat_id, _), result in zip(items, results, strict=True):
        assert result["status"] == "succeeded", result
        assert result["metrics"]["model_calls"] == 1, result
        assert (
            api("GET", f"/api/chats/{chat_id}/")["current_revision"]["id"] == result["result_revision_id"]
        )
    return [r["metrics"] for r in results]


report = {"profile": "fake-real-Celery-cached-fixture", "sequential": [], "batches": {}}
for _ in range(5):
    item = submit()
    report["sequential"].extend(await_batch([item]))
    api("DELETE", f"/api/chats/{item[0]}/")
for count in (1, 3, 10):
    items = [submit() for _ in range(count)]
    report["batches"][str(count)] = await_batch(items)
    for chat, _ in items:
        api("DELETE", f"/api/chats/{chat}/")
report["budget"] = api("GET", "/api/session/")["budget"]
assert (
    report["budget"]["spent_usd"] == report["budget"]["reserved_usd"] == report["budget"]["unknown_usd"] == 0
)
(ROOT / ".data" / "queue-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
