"""Bound raw JSON before decoding; Django's request.body limit misses DRF streams."""

from io import BytesIO

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class BoundedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        if limit is not None:
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise RequestDataTooBig("JSON body exceeds the configured byte limit.")
            stream = BytesIO(raw)
        try:
            return super().parse(stream, media_type, parser_context)
        except RecursionError as exc:
            raise ParseError("Слишком большая вложенность JSON.") from exc
