"""Continuously export read-only durable state; no provider calls or recovery actions."""
import signal
import threading

from django.core.management.base import BaseCommand

from gameforge import telemetry
from studio.observability import collect


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        stop = threading.Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        telemetry.get_state()
        while not stop.is_set():
            collect()
            if options['once']:
                break
            stop.wait(30)
        telemetry.flush()
        telemetry.shutdown()
