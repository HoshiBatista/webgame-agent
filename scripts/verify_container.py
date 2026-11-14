"""Paid-call-free HTTP acceptance for an explicitly fake installation."""

import argparse
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


def run(api, chat, prompt, *, source=None):
    start = time.monotonic()
    payload = {"prompt": prompt, "idempotency_key": str(uuid.uuid4()), "model_profile": ""}
    if source is not None:
        payload.update(source_revision_id=source["id"], source_artifact_hash=source["artifact_hash"])
    item = api("POST", f"/api/chats/{chat}/runs/", payload)
    deadline = time.monotonic() + 90
    while item["status"] in ("queued", "generating", "checking") and time.monotonic() < deadline:
        time.sleep(0.25)
        item = api("GET", f"/api/runs/{item['id']}/")
    assert item["status"] == "succeeded", item
    assert item["provider"] == "fake" and item["model"] == "fixture", item
    return item, round(time.monotonic() - start, 3)


def verify(base, preview_origin, username, password):
    with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
        ready_deadline = time.monotonic() + 30
        while True:
            try:
                response = client.get("/api/health/")
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > ready_deadline:
                raise RuntimeError("App did not become ready within 30 seconds")
            time.sleep(0.25)
        csrf = client.get("/api/session/").json()["csrfToken"]
        assert (
            client.post(
                "/api/login/",
                json={
                    "username": username,
                    "password": password,
                },
            ).status_code
            == 403
        )
        login = client.post(
            "/api/login/",
            json={
                "username": username,
                "password": password,
            },
            headers={"X-CSRFToken": csrf},
        )
        login.raise_for_status()
        session = login.json()
        if session["capabilities"]["provider"] != "fake" or session["capabilities"]["model"] != "fixture":
            raise RuntimeError("Refusing to run: this acceptance permits only the free fixture provider/model.")
        client.headers["X-CSRFToken"] = session["csrfToken"]

        def api(method, path, data=None):
            response = client.request(method, path, json=data)
            response.raise_for_status()
            return response.json() if response.content else None

        chat = api("POST", "/api/chats/", {"title": "HTTP acceptance fixture", "audience": "children"})
        create, create_seconds = run(api, chat["id"], "Infrastructure fixture: create a small test game")
        detail = api("GET", f"/api/chats/{chat['id']}/")
        revision = detail["current_revision"]
        assert revision["verification"] == "automatic"
        assert "заглушка" in revision["title"]
        html = client.get(revision["export_url"])
        html.raise_for_status()
        assert hashlib.sha256(html.content).hexdigest() == revision["artifact_hash"]
        assert urlparse(revision["preview_url"]).netloc == urlparse(preview_origin).netloc
        assert urlparse(preview_origin).netloc != urlparse(base).netloc
        preview = httpx.get(revision["preview_url"], timeout=15, trust_env=False)
        assert preview.status_code == 200 and preview.content == html.content
        assert "set-cookie" not in preview.headers
        assert "connect-src 'none'" in preview.headers["content-security-policy"]
        assert "sandbox allow-scripts" in preview.headers["content-security-policy"]
        assert httpx.get(base + urlparse(revision["preview_url"]).path, trust_env=False).status_code == 403
        assert httpx.get(preview_origin + "/api/session/", trust_env=False).status_code == 404
        assert client.get("/").status_code == 200
        source_before = api("GET", f"/api/revisions/{revision['id']}/source/")
        publication = api(
            "POST", "/api/publications/", {"chat_id": chat["id"], "title": "Immutable fixture snapshot"}
        )
        for identity, code in (({}, "source_required"), ({"source_revision_id": revision["id"],
                                "source_artifact_hash": "0" * 64}, "source_changed")):
            rejected = client.post(f"/api/chats/{chat['id']}/runs/", json={
                "prompt": "Change background", "model_profile": "", "idempotency_key": str(uuid.uuid4()), **identity,
            })
            assert rejected.status_code == 409 and rejected.json()["error"]["code"] == code
        assert len(api("GET", f"/api/chats/{chat['id']}/")["runs"]) == 1
        edit, edit_seconds = run(api, chat["id"], "Change only the background color", source=revision)
        assert edit["operation"] == "edit" and edit["source_revision_id"] == revision["id"]
        current = api("GET", f"/api/chats/{chat['id']}/")["current_revision"]
        source_after = api("GET", f"/api/revisions/{current['id']}/source/")
        before, after = source_before["files"], source_after["files"]
        assert set(before) == set(after)
        assert {path for path in before if before[path] != after[path]} == {"styles.css"}
        assert api("GET", f"/api/publications/{publication['id']}/")["artifact_hash"] == revision["artifact_hash"]
        remix = api("POST", f"/api/publications/{publication['id']}/remix/", {})
        assert remix["messages"] == []
        assert remix["current_revision"]["artifact_hash"] == revision["artifact_hash"]
        assert remix["current_revision"]["artifact_hash"] != current["artifact_hash"]
        api("PUT", f"/api/publications/{publication['id']}/like/", {"liked": True})
        assert api("PUT", f"/api/publications/{publication['id']}/like/", {"liked": True})["likes"] == 1
        updated = api("PATCH", f"/api/publications/{publication['id']}/", {"revision_id": current["id"]})
        assert updated["artifact_hash"] == current["artifact_hash"]
        edited_export = client.get(current["export_url"])
        edited_export.raise_for_status()
        assert hashlib.sha256(edited_export.content).hexdigest() == current["artifact_hash"]
        events = client.get(create["events_url"]).text
        ids = [int(line[4:]) for line in events.splitlines() if line.startswith("id: ")]
        assert ids and ids == sorted(set(ids))
        assert "event: progress" in events
        assert "event: progress" not in client.get(create["events_url"], params={"after": ids[-1]}).text
        api("DELETE", f"/api/chats/{chat['id']}/")
        assert api("GET", f"/api/publications/{publication['id']}/")["artifact_hash"] == current["artifact_hash"]
        assert client.get(f"/api/chats/{chat['id']}/").status_code == 404
        with httpx.Client(base_url=base, trust_env=False) as guest:
            assert guest.get(f"/api/publications/{publication['id']}/").status_code == 200
            assert guest.get(f"/api/runs/{create['id']}/diagnostics/").status_code == 403
            assert guest.get(f"/api/chats/{remix['id']}/").status_code == 403
        budget = api("GET", "/api/session/")["budget"]
        assert budget["spent_usd"] == 0 and budget["reserved_usd"] == 0 and budget["unknown_usd"] == 0
        result = {
            "profile": "http-fake-real-worker-and-validator",
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
                "source-required",
                "stale-source-rejected",
                "edited-export-hash",
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
        api("DELETE", f"/api/publications/{publication['id']}/")
        api("DELETE", f"/api/chats/{remix['id']}/")
        return result


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.environ.get("CONTAINER_TEST_ORIGIN", "http://127.0.0.1:8080"))
    parser.add_argument("--preview-origin", default="http://localhost:8081")
    parser.add_argument("--output", type=Path, default=ROOT / ".data/container-verification.json")
    args = parser.parse_args()
    result = verify(args.origin, args.preview_origin.rstrip("/"),
                    os.environ["DJANGO_SUPERUSER_USERNAME"], os.environ["DJANGO_SUPERUSER_PASSWORD"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
