"""Catalog discovery uses only bounded read-only RPCs, never paid inference."""

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from prompt2play.workers import model_catalog


def fake_codex(tmp_path: Path, mode: str = "ok") -> Path:
    executable = tmp_path / "codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        f"MODE={mode!r}\nTRACE={str(tmp_path / 'rpc.jsonl')!r}\n"
        r"""
import json,sys,time
initialized=False
for line in sys.stdin:
    request=json.loads(line)
    with open(TRACE,'a') as out: out.write(json.dumps(request)+'\n')
    method=request['method']
    assert method in ['initialize','initialized','model/list'], method
    if method=='initialize': result={}
    elif method=='initialized': initialized=True; continue
    else:
        assert initialized
        assert request['params']['includeHidden'] is False
        if MODE=='hang': time.sleep(30)
        if MODE=='error':
            print(json.dumps({'id':request['id'],'error':{'message':'private-error-fixture'}}),flush=True)
            continue
        result={'data':[{'id':'other-id','model':'fixture-first','displayName':'First','isDefault':True,
                         'private-field':'never-publish'}], 'nextCursor':'page-two'}
        if request['params']['cursor']:
            result={'data':[{'model':'fixture-second','displayName':'Second'},
                            {'model':'fixture-hidden','displayName':'Hidden','hidden':True}],
                    'nextCursor':None}
        if MODE=='bad': result={'data':'not-a-list'}
        if MODE=='loop': result['nextCursor']='page-two'
        print(json.dumps({'method':'notice','params':{}}),flush=True)
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
"""
    )
    executable.chmod(0o700)
    return executable


def test_read_only_handshake_pagination_and_public_fields(tmp_path: Path) -> None:
    result = model_catalog.discover_codex_models(str(fake_codex(tmp_path)))
    assert result == [
        {"id": "fixture-first", "label": "First", "is_default": True},
        {"id": "fixture-second", "label": "Second", "is_default": False},
    ]
    requests = [json.loads(line) for line in (tmp_path / "rpc.jsonl").read_text().splitlines()]
    assert [row["method"] for row in requests] == [
        "initialize",
        "initialized",
        "model/list",
        "model/list",
    ]
    assert requests[-1]["params"]["cursor"] == "page-two"


@pytest.mark.parametrize(
    "mode,reason", [("error", "rpc_error"), ("bad", "invalid_response"), ("loop", "invalid_cursor")]
)
def test_discovery_rejects_errors_without_leaking_provider_text(
    tmp_path: Path, mode: str, reason: str
) -> None:
    with pytest.raises(model_catalog.CatalogUnavailable, match=reason):
        model_catalog.discover_codex_models(str(fake_codex(tmp_path, mode)))


def test_discovery_timeout_reaps_child(tmp_path: Path) -> None:
    started = time.monotonic()
    with pytest.raises(model_catalog.CatalogUnavailable, match="timeout"):
        model_catalog.discover_codex_models(str(fake_codex(tmp_path, "hang")), timeout=1)
    assert time.monotonic() - started < 3
    assert '"method": "model/list"' in (tmp_path / "rpc.jsonl").read_text()


def test_failed_refresh_clears_stale_account_catalog_and_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    now = [100.0]

    def discover(executable: str) -> list[dict[str, Any]]:
        calls.append(executable)
        if len(calls) > 1:
            raise model_catalog.CatalogUnavailable("rpc_error")
        return [{"id": "fixture", "label": "Fixture", "is_default": True}]

    monkeypatch.setattr(model_catalog, "discover_codex_models", discover)
    monkeypatch.setattr("prompt2play.workers.model_catalog.time.monotonic", lambda: now[0])
    catalog = model_catalog.CodexModelCatalog("fixture-executable")
    assert catalog.capabilities()["model_catalog_status"] == "ready"
    assert catalog.capabilities()["codex_models"]
    assert len(calls) == 1
    now[0] += 301
    assert catalog.capabilities()["model_catalog_status"] == "unavailable"
    assert catalog.capabilities()["codex_models"] == []
    assert len(calls) == 2
    now[0] += 61
    catalog.capabilities()
    assert len(calls) == 3


@pytest.mark.parametrize("mutation", ["secret", "duplicate", "unavailable", "too_many"])
def test_catalog_claim_rejects_invalid_metadata(mutation: str) -> None:
    from prompt2play.adapters.django.forge.serializers import ClaimSerializer

    catalog: dict[str, Any] = {
        "providers": ["codex"],
        "model_catalog_status": "ready",
        "model_catalog_checked_at": "2026-10-12T00:00:00+00:00",
        "codex_models": [{"id": "fixture", "label": "Fixture", "is_default": True}],
    }
    if mutation == "secret":
        catalog["codex_models"][0]["api_key"] = "private-fixture"
    elif mutation == "duplicate":
        catalog["codex_models"] *= 2
    elif mutation == "unavailable":
        catalog["model_catalog_status"] = "unavailable"
    else:
        catalog["codex_models"] *= 65
    serializer = ClaimSerializer(data={"capabilities": catalog})
    assert not serializer.is_valid()
