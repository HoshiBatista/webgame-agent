from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from studio.models import Chat, Invocation, Publication, Revision, Run, User


@pytest.mark.django_db
def test_retirement_removes_only_unsupported_artifacts_and_keeps_call_liability():
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
    call_command("retire_games", apply=True, stdout=StringIO())
    chat.refresh_from_db()
    invocation.refresh_from_db()
    assert chat.current_revision_id is None and Revision.objects.filter(pk=current.id).exists()
    assert not Revision.objects.filter(pk=old.id).exists() and not Publication.objects.exists()
    assert invocation.state == "unknown" and invocation.request == {"saved": "original"}
    assert invocation.reservation_usd == Decimal("0.3") and invocation.revision_id is None
    assert Run.objects.filter(pk=run.id).exists() and User.objects.filter(pk=user.id).exists()
    assert chat.deleted_at is None


@pytest.mark.django_db
def test_retirement_hides_old_empty_chats_and_retains_financial_history():
    user = User.objects.create_user(username='old-chat-owner')
    chat = Chat.objects.create(owner=user)
    new_chat = Chat.objects.create(owner=user)
    already_retired = Chat.objects.create(owner=user)
    mixed = Chat.objects.create(owner=user)
    run = Run.objects.create(chat=chat, operation='create', prompt='old', provider='relay',
                             status='unverified', pipeline_version=7,
                             idempotency_key='old', request_fingerprint='old')
    old = Revision.objects.create(chat=chat, run=run, number=1, files={}, html='old',
                                  artifact_hash='a' * 64, pipeline_version=7)
    call = Invocation.objects.create(run=run, attempt=1, state='unknown',
                                     request={'original': True}, reservation_usd='0.3', revision=old)
    for target, version in [(already_retired, 7), (mixed, 7), (mixed, 8)]:
        Run.objects.create(chat=target, operation='create', prompt='history', provider='fake',
                           status='failed', pipeline_version=version,
                           idempotency_key=str(version), request_fingerprint='history')
    call_command('retire_games', apply=True, stdout=StringIO())
    chat.refresh_from_db()
    new_chat.refresh_from_db()
    call.refresh_from_db()
    already_retired.refresh_from_db()
    mixed.refresh_from_db()
    assert chat.deleted_at is not None and new_chat.deleted_at is None
    assert already_retired.deleted_at is not None and mixed.deleted_at is None
    assert call.state == 'unknown' and call.request == {'original': True}
    assert call.reservation_usd == Decimal('0.3') and Run.objects.filter(pk=run.id).exists()


@pytest.mark.django_db
def test_retirement_is_blocked_until_active_call_accounting_is_safe():
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
        call_command("retire_games", apply=True, stdout=StringIO())
