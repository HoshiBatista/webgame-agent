"""Remove unsupported game artifacts while retaining users, prompts and call accounting."""

import json
import os
from pathlib import Path

from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from generation.schema import CONTRACT_VERSION
from studio.models import Chat, CheckReport, Invocation, Publication, Revision, Run


class Command(BaseCommand):
    help = "List unsupported games; --apply removes artifacts and marks publications unavailable, preserving invocation accounting."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--backup', help='New private JSON backup path; required with --apply.')

    @transaction.atomic
    def handle(self, *args, **options):
        # Same lock order as the writer: chat then run, before checking activity.
        list(Chat.objects.select_for_update().order_by('id').values_list('id', flat=True))
        list(Run.objects.select_for_update().order_by('id').values_list('id', flat=True))
        if Run.objects.filter(status__in=Run.ACTIVE).exists() or Invocation.objects.filter(state__in=['reserved', 'sent']).exists():
            raise CommandError('Wait for active operations/receipts before retiring games.')
        unsupported = Revision.objects.filter(~Q(pipeline_version=CONTRACT_VERSION))
        publications = Publication.objects.filter(revision__in=unsupported)
        old_chats = set(unsupported.exclude(chat_id=None).values_list('chat_id', flat=True))
        old_chats.update(Run.objects.exclude(pipeline_version=CONTRACT_VERSION).values_list('chat_id', flat=True))
        empty_old_chats = Chat.objects.filter(id__in=old_chats, deleted_at__isnull=True).exclude(
            revisions__pipeline_version=CONTRACT_VERSION,
        ).exclude(runs__pipeline_version=CONTRACT_VERSION)
        counts = {'revisions': unsupported.count(), 'publications': publications.count(), 'chats': empty_old_chats.count()}
        if options['apply']:
            if not options['backup']:
                raise CommandError('--apply requires a new --backup path before removing artifacts.')
            backup = Path(options['backup']).expanduser()
            rows = [*unsupported, *CheckReport.objects.filter(revision__in=unsupported), *publications, *Chat.objects.filter(id__in=old_chats),
                    *Run.objects.filter(chat_id__in=old_chats), *Invocation.objects.filter(run__chat_id__in=old_chats)]
            try:
                descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    json.dump({'version':1, 'created_at':timezone.now().isoformat(),
                               'target_pipeline':CONTRACT_VERSION, 'inventory':counts,
                               'objects':json.loads(serializers.serialize('json', rows))}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                parent = os.open(backup.parent, os.O_RDONLY)
                try:
                    os.fsync(parent)
                finally:
                    os.close(parent)
            except OSError as exc:
                raise CommandError('Could not create a new private backup; no artifacts removed.') from exc
            publications.update(revision=None, unavailable_at=timezone.now())
            unsupported.delete()
            empty_old_chats.update(deleted_at=timezone.now())
        self.stdout.write(('Removed ' if options['apply'] else 'Would remove ') + str(counts))
