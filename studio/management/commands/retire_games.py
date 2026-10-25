"""Remove unsupported game artifacts while retaining users, prompts and call accounting."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from generation.schema import CONTRACT_VERSION
from studio.models import Chat, Invocation, Publication, Revision, Run


class Command(BaseCommand):
    help = "List unsupported games; --apply removes their artifacts/publications, preserving invocation accounting."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

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
            publications.delete()
            unsupported.delete()
            empty_old_chats.update(deleted_at=timezone.now())
        self.stdout.write(('Removed ' if options['apply'] else 'Would remove ') + str(counts))
