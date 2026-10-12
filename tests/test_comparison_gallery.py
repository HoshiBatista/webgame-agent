"""Generated HTML gets an isolated route; receipts and private files do not."""

import json
import runpy
from pathlib import Path


def test_gallery_serves_only_declared_games_and_safe_png(tmp_path: Path) -> None:
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/serve_comparison.py"))
    root = tmp_path / "comparison"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps({"cases": [{"id": "a", "revision": "", "prompt": "<script>bad()</script>"}]})
    )
    folder = root / "adaptive-a-new"
    folder.mkdir()
    (folder / "index.html").write_text("untrusted game")
    (folder / "invocations.json").write_text('{"private":"receipt"}')
    frames = folder / "independent-1"
    frames.mkdir()
    (frames / "start-1280.png").write_bytes(b"fixture")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    (frames / "final-390.png").symlink_to(outside)
    assets = module["allowed_assets"](root)
    assert set(assets) == {"/games/adaptive-a-new", "/frames/adaptive-a-new/start-1280.png"}
    rendered = module["gallery"](root, assets).decode()
    assert '<iframe src="/games/adaptive-a-new"' in rendered
    assert 'sandbox="allow-scripts"' in rendered
    assert "allow-same-origin" not in rendered
    assert "<script>bad()" not in rendered
    assert "&lt;script&gt;bad()&lt;/script&gt;" in rendered
    assert "не подтверждены" in rendered
    assert "connect-src 'none'" in module["GAME_CSP"]
    assert "sandbox allow-scripts" in module["GAME_CSP"]
