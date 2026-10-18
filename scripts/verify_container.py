"""Paid-call-free HTTP acceptance for an explicitly fake Compose profile."""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
BASE = os.environ.get("CONTAINER_TEST_ORIGIN", "http://127.0.0.1:8080")
client = httpx.Client(base_url=BASE, timeout=15, trust_env=False)
ready_deadline = time.monotonic() + 30
while True:
    try:
        response = client.get("/api/health/")
        if response.status_code == 200:
            break
    except httpx.HTTPError:
        pass
    if time.monotonic() > ready_deadline:
        raise RuntimeError("Compose app did not become ready within 30 seconds")
    time.sleep(0.25)
csrf = client.get("/api/session/").json()["csrfToken"]
assert (
    client.post(
        "/api/login/",
        json={
            "username": os.environ["DJANGO_SUPERUSER_USERNAME"],
            "password": os.environ["DJANGO_SUPERUSER_PASSWORD"],
        },
    ).status_code
    == 403
)
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
assert session["capabilities"]["provider"] == "fake", (
    "Refusing to run: this acceptance permits only the free fixture provider."
)
assert session["capabilities"]["model"] == "fixture"
client.headers["X-CSRFToken"] = session["csrfToken"]


def api(method, path, data=None):
    response = client.request(method, path, json=data)
    response.raise_for_status()
    return response.json() if response.content else None


def run(chat, prompt):
    start = time.monotonic()
    item = api("POST", f"/api/chats/{chat}/runs/", {"prompt": prompt, "idempotency_key": str(uuid.uuid4())})
    deadline = time.monotonic() + 90
    while item["status"] in ("queued", "generating", "checking") and time.monotonic() < deadline:
        time.sleep(0.25)
        item = api("GET", f"/api/runs/{item['id']}/")
    assert item["status"] == "succeeded", item
    return item, round(time.monotonic() - start, 3)


chat = api("POST", "/api/chats/", {"title": "Compose acceptance fixture", "audience": "children"})
create, create_seconds = run(chat["id"], "Infrastructure fixture: create a small test game")
detail = api("GET", f"/api/chats/{chat['id']}/")
revision = detail["current_revision"]
assert revision["verification"] == "automatic"
assert "заглушка" in revision["title"]
html = client.get(revision["export_url"])
html.raise_for_status()
assert hashlib.sha256(html.content).hexdigest() == revision["artifact_hash"]
preview = httpx.get(revision["preview_url"], timeout=15, trust_env=False)
assert preview.status_code == 200 and preview.content == html.content
assert "set-cookie" not in preview.headers
assert "connect-src 'none'" in preview.headers["content-security-policy"]
assert "sandbox allow-scripts" in preview.headers["content-security-policy"]
assert httpx.get(BASE + urlparse(revision["preview_url"]).path, trust_env=False).status_code == 403
assert httpx.get("http://localhost:8081/api/session/", trust_env=False).status_code == 404
assert client.get("/").status_code == 200
source_before = api("GET", f"/api/revisions/{revision['id']}/source/")
publication = api(
    "POST", "/api/publications/", {"chat_id": chat["id"], "title": "Immutable fixture snapshot"}
)
edit, edit_seconds = run(chat["id"], "Change only the background color")
current = api("GET", f"/api/chats/{chat['id']}/")["current_revision"]
source_after = api("GET", f"/api/revisions/{current['id']}/source/")
assert source_before["files"]["game.js"] == source_after["files"]["game.js"]
assert source_before["files"]["index.html"] == source_after["files"]["index.html"]
assert source_before["files"]["styles.css"] != source_after["files"]["styles.css"]
assert api("GET", f"/api/publications/{publication['id']}/")["artifact_hash"] == revision["artifact_hash"]
remix = api("POST", f"/api/publications/{publication['id']}/remix/", {})
assert remix["messages"] == []
assert remix["current_revision"]["artifact_hash"] == revision["artifact_hash"]
assert remix["current_revision"]["artifact_hash"] != current["artifact_hash"]
api("PUT", f"/api/publications/{publication['id']}/like/", {"liked": True})
assert api("PUT", f"/api/publications/{publication['id']}/like/", {"liked": True})["likes"] == 1
updated = api("PATCH", f"/api/publications/{publication['id']}/", {"revision_id": current["id"]})
assert updated["artifact_hash"] == current["artifact_hash"]
events = client.get(create["events_url"]).text
ids = [int(line[4:]) for line in events.splitlines() if line.startswith("id: ")]
assert ids and ids == sorted(set(ids))
assert "event: progress" not in client.get(create["events_url"], params={"after": ids[-1]}).text
api("DELETE", f"/api/chats/{chat['id']}/")
assert api("GET", f"/api/publications/{publication['id']}/")["artifact_hash"] == current["artifact_hash"]
assert client.get(f"/api/chats/{chat['id']}/").status_code == 404
with httpx.Client(base_url=BASE, trust_env=False) as guest:
    assert guest.get(f"/api/publications/{publication['id']}/").status_code == 200
    assert guest.get(f"/api/runs/{create['id']}/diagnostics/").status_code == 403
    assert guest.get(f"/api/chats/{remix['id']}/").status_code == 403
budget = api("GET", "/api/session/")["budget"]
assert budget["spent_usd"] == 0 and budget["reserved_usd"] == 0 and budget["unknown_usd"] == 0
result = {
    "profile": "docker-compose-fake-only",
    "create_seconds": create_seconds,
    "edit_seconds": edit_seconds,
    "create_metrics": create["metrics"],
    "edit_metrics": edit["metrics"],
    "create_run": create["id"],
    "edit_run": edit["id"],
    "publication": publication["id"],
    "remix": remix["id"],
    "revision_hash_before": revision["artifact_hash"],
    "revision_hash_after": current["artifact_hash"],
    "budget": budget,
    "checks": [
        "csrf-login",
        "session-auth",
        "create-automatic-browser-acceptance",
        "exact-export-preview-bytes",
        "separate-preview-host",
        "preview-no-session-cookie",
        "preview-csp-sandbox",
        "preview-no-api",
        "local-edit-unchanged-mechanics",
        "immutable-publication",
        "published-remix-not-private-draft",
        "empty-remix-prompts",
        "idempotent-like",
        "explicit-publish-update",
        "persisted-sse-reconnect",
        "delete-chat-keeps-publication",
        "guest-private-access-denied",
    ],
}
(ROOT / ".data").mkdir(exist_ok=True)
(ROOT / ".data" / "container-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
