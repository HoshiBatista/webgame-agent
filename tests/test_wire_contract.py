import json
from pathlib import Path

from generation.relay_api.protocol import digest, validate_receipt


def test_canonical_v1_receipt():
    fixture = json.loads((Path(__file__).parent / "fixtures/relay-v1.json").read_text())
    validate_receipt(fixture["receipt"])
    assert digest(fixture["receipt"]) == fixture["sha256"]
