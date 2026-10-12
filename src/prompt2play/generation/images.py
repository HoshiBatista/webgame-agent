"""Bounded immutable PNG inputs. Pixels never become instructions or host paths."""

from __future__ import annotations

import base64
import hashlib
import re
import struct
import zlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageInput:
    name: str
    data: bytes

    def metadata(self) -> dict[str, str | int]:
        if not re.fullmatch(r"[a-z0-9_-]{1,100}\.png", self.name):
            raise ValueError("Invalid screenshot name")
        if not 24 <= len(self.data) <= 2_000_000 or not self.data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid or oversized PNG input")
        offset, chunks = 8, []
        while offset + 12 <= len(self.data):
            length = struct.unpack(">I", self.data[offset : offset + 4])[0]
            end = offset + 12 + length
            if end > len(self.data):
                raise ValueError("Truncated PNG chunk")
            kind = self.data[offset + 4 : offset + 8]
            actual_crc = struct.unpack(">I", self.data[end - 4 : end])[0]
            if zlib.crc32(self.data[offset + 4 : end - 4]) != actual_crc:
                raise ValueError("Corrupt PNG chunk")
            chunks.append(kind)
            offset = end
        if (
            offset != len(self.data)
            or not chunks
            or chunks[0] != b"IHDR"
            or chunks[-1] != b"IEND"
            or b"IDAT" not in chunks
            or chunks.count(b"IHDR") != 1
            or chunks.count(b"IEND") != 1
            or self.data[8:12] != b"\0\0\0\r"
        ):
            raise ValueError("Invalid PNG structure")
        width, height = struct.unpack(">II", self.data[16:24])
        if not 1 <= width <= 4096 or not 1 <= height <= 4096 or width * height > 8_000_000:
            raise ValueError("Screenshot exceeds its pixel envelope")
        return {
            "name": self.name,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "bytes": len(self.data),
            "width": width,
            "height": height,
        }

    def wire(self) -> dict[str, str]:
        self.metadata()
        return {"name": self.name, "base64": base64.b64encode(self.data).decode("ascii")}


def image_metadata(images: list[ImageInput]) -> list[dict[str, str | int]]:
    if not 1 <= len(images) <= 6 or len({i.name for i in images}) != len(images):
        raise ValueError("Image review needs one to six distinct screenshots")
    if sum(len(i.data) for i in images) > 8_000_000:
        raise ValueError("Image inputs exceed their total byte envelope")
    return [i.metadata() for i in images]
