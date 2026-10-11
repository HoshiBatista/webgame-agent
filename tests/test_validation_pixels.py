"""Pixel comparisons tolerate encoding noise while retaining material changes."""

from __future__ import annotations

import binascii
import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from prompt2play.validation import IsolatedValidator


def png(value: int, changed: int = 0) -> bytes:
    width, height = 32, 4
    pixels = bytes([value, 50, 80] * changed + [20, 50, 80] * (width * height - changed))
    raw = b"".join(b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))

    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", binascii.crc32(name + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_pixel_noise_is_not_progress_and_material_pixels_are_observable(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for trusted PNG probe; no game executes in this test")
    names = {"base": png(20), "noise": png(21, 3), "small": png(160, 8), "progress": png(160, 32)}
    for name, data in names.items():
        (tmp_path / f"{name}.png").write_bytes(data)
    probe = IsolatedValidator().runtime_path.parent / "pixel_probe.mjs"
    script = """
      import fs from 'node:fs';
      const {compareImages} = await import(process.argv[1]);
      const base = fs.readFileSync(process.argv[2] + '/base.png');
      const result = Object.fromEntries(['noise','small','progress'].map(name => [name,
        compareImages(base, fs.readFileSync(process.argv[2] + '/' + name + '.png'))]));
      process.stdout.write(JSON.stringify(result));
    """
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, probe.as_uri(), str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    observed = json.loads(result.stdout)
    assert observed["noise"]["stable"] is True
    assert observed["small"]["stable"] is False
    assert observed["small"]["visible_changed"] is False
    assert observed["progress"]["visible_changed"] is True
    assert observed["progress"]["changed_pixels"] == 32
