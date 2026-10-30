from contextlib import nullcontext
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from studio.models import Chat, CheckReport, Invocation, Publication, Revision, Run, User


@pytest.mark.django_db
def test_retirement_removes_only_unsupported_artifacts_and_keeps_call_liability(tmp_path):
    user = User.objects.create_user(username="retirement-maker")
    chat = Chat.objects.create(owner=user)
    run = Run.objects.create(
        chat=chat,
        operation="create",
        prompt="old",
        provider="relay",
        model="fixture",
        status="needs_attention",
        idempotency_key="old",
        request_fingerprint="old",
        pipeline_version=7,
    )
    old = Revision.objects.create(
        chat=chat, run=run, number=1, files={}, html="old", artifact_hash="a" * 64, pipeline_version=7
    )
    current = Revision.objects.create(chat=chat, number=2, files={}, html="current", artifact_hash="b" * 64)
    chat.current_revision = old
    chat.save(update_fields=["current_revision"])
    Publication.objects.create(owner=user, revision=old, title="Old", source_chat=chat)
    invocation = Invocation.objects.create(
        run=run,
        attempt=1,
        state="unknown",
        request={"saved": "original"},
        reservation_usd="0.300000",
        revision=old,
    )
    call_command("retire_games", stdout=StringIO())
    assert Revision.objects.filter(pk=old.id).exists()
    call_command("retire_games", apply=True, backup=str(tmp_path / "retired.json"), stdout=StringIO())
    chat.refresh_from_db()
    invocation.refresh_from_db()
    assert chat.current_revision_id is None and Revision.objects.filter(pk=current.id).exists()
    assert (
        not Revision.objects.filter(pk=old.id).exists()
        and Publication.objects.get().unavailable_at is not None
    )
    assert Publication.objects.get().revision_id is None
    assert invocation.state == "unknown" and invocation.request == {"saved": "original"}
    assert invocation.reservation_usd == Decimal("0.3") and invocation.revision_id is None
    assert Run.objects.filter(pk=run.id).exists() and User.objects.filter(pk=user.id).exists()
    assert chat.deleted_at is None


@pytest.mark.django_db
def test_retirement_hides_old_empty_chats_and_retains_financial_history(tmp_path):
    user = User.objects.create_user(username="old-chat-owner")
    chat = Chat.objects.create(owner=user)
    new_chat = Chat.objects.create(owner=user)
    already_retired = Chat.objects.create(owner=user)
    mixed = Chat.objects.create(owner=user)
    run = Run.objects.create(
        chat=chat,
        operation="create",
        prompt="old",
        provider="relay",
        status="unverified",
        pipeline_version=7,
        idempotency_key="old",
        request_fingerprint="old",
    )
    old = Revision.objects.create(
        chat=chat, run=run, number=1, files={}, html="old", artifact_hash="a" * 64, pipeline_version=7
    )
    call = Invocation.objects.create(
        run=run, attempt=1, state="unknown", request={"original": True}, reservation_usd="0.3", revision=old
    )
    for target, version in [(already_retired, 7), (mixed, 7), (mixed, 9)]:
        Run.objects.create(
            chat=target,
            operation="create",
            prompt="history",
            provider="fake",
            status="failed",
            pipeline_version=version,
            idempotency_key=str(version),
            request_fingerprint="history",
        )
    call_command("retire_games", apply=True, backup=str(tmp_path / "retired.json"), stdout=StringIO())
    chat.refresh_from_db()
    new_chat.refresh_from_db()
    call.refresh_from_db()
    already_retired.refresh_from_db()
    mixed.refresh_from_db()
    assert chat.deleted_at is not None and new_chat.deleted_at is None
    assert already_retired.deleted_at is not None and mixed.deleted_at is None
    assert call.state == "unknown" and call.request == {"original": True}
    assert call.reservation_usd == Decimal("0.3") and Run.objects.filter(pk=run.id).exists()


@pytest.mark.django_db
def test_retirement_is_blocked_until_active_call_accounting_is_safe(tmp_path):
    chat = Chat.objects.create(owner=User.objects.create_user(username="busy-retirement"))
    Run.objects.create(
        chat=chat,
        operation="create",
        prompt="active",
        provider="fake",
        idempotency_key="active",
        request_fingerprint="active",
    )
    with pytest.raises(CommandError):
        call_command("retire_games", apply=True, backup=str(tmp_path / "retired.json"), stdout=StringIO())


@pytest.mark.django_db
@pytest.mark.parametrize("fault", ["missing_path", "existing_path", "write_failure"])
def test_retirement_requires_a_new_durable_backup_before_any_deletion(tmp_path, fault):
    from unittest.mock import patch

    chat = Chat.objects.create(owner=User.objects.create_user(username="backup-owner"))
    old = Revision.objects.create(
        chat=chat,
        number=1,
        files={"game.js": "private"},
        html="old",
        artifact_hash="a" * 64,
        pipeline_version=8,
    )
    destination = tmp_path / "backup.json"
    if fault == "existing_path":
        destination.write_text("existing backup")
    with (
        patch("studio.management.commands.retire_games.os.fsync", side_effect=OSError("disk"))
        if fault == "write_failure"
        else nullcontext()
    ):
        with pytest.raises(CommandError):
            call_command(
                "retire_games",
                apply=True,
                backup=None if fault == "missing_path" else str(destination),
                stdout=StringIO(),
            )
    assert Revision.objects.filter(pk=old.id).exists()
    if fault == "existing_path":
        assert destination.read_text() == "existing backup"


@pytest.mark.django_db
def test_retired_public_links_are_explicitly_gone_and_accounting_is_backed_up(tmp_path):
    import json
    import stat

    from django.test import Client

    user = User.objects.create_user(username="gone-owner")
    chat = Chat.objects.create(owner=user)
    run = Run.objects.create(
        chat=chat,
        operation="create",
        prompt="old",
        provider="codex_api",
        status="unknown",
        pipeline_version=8,
        idempotency_key="old",
        request_fingerprint="old",
    )
    old = Revision.objects.create(
        chat=chat,
        run=run,
        number=1,
        files={"game.js": "original"},
        html="old",
        artifact_hash="a" * 64,
        pipeline_version=8,
        accepted=True,
    )
    publication = Publication.objects.create(owner=user, source_chat=chat, revision=old, title="Old")
    invocation = Invocation.objects.create(
        run=run,
        attempt=1,
        state="unknown",
        request={"uuid": "same-request"},
        reservation_usd="0.30",
        revision=old,
    )
    client = Client()
    client.force_login(user)
    for suffix in ["", "thumbnail/"]:
        response = client.get(f"/api/publications/{publication.id}/{suffix}")
        assert response.status_code == 410
    assert client.get("/api/publications/").json()["results"] == []
    CheckReport.objects.create(revision=old, status="unverified", identity="historic",
                               checks=[{"old":"scenario"}], facts=[{"old":"evidence"}])
    destination = tmp_path / "backup.json"
    call_command("retire_games", apply=True, backup=str(destination), stdout=StringIO())
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    snapshot = json.loads(destination.read_text())
    assert snapshot["inventory"]["revisions"] == 1
    proof = next(o for o in snapshot["objects"] if o["model"] == "studio.checkreport")
    assert proof["fields"]["facts"] == [{"old":"evidence"}] and proof["fields"]["identity"] == "historic"
    saved = next(o for o in snapshot["objects"] if o["model"] == "studio.invocation")
    assert saved["fields"]["state"] == "unknown" and saved["fields"]["request"] == {"uuid": "same-request"}
    assert client.get(f"/api/publications/{publication.id}/").status_code == 410
    assert (
        client.post(
            f"/api/publications/{publication.id}/remix/", {}, content_type="application/json"
        ).status_code
        == 410
    )
    invocation.refresh_from_db()
    assert (
        invocation.state == "unknown"
        and invocation.revision_id is None
        and invocation.request == {"uuid": "same-request"}
    )
    assert not Chat.objects.exclude(pk=chat.pk).exists()
