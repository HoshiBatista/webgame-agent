"""Loopback-only review gallery. Serves comparison games/PNG, never private logs."""

from __future__ import annotations

import argparse
import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

GAME_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; font-src data:; media-src data:; connect-src 'none'; "
    "form-action 'none'; base-uri 'none'; sandbox allow-scripts"
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def allowed_assets(root: Path) -> dict[str, tuple[Path, str]]:
    result = {}
    for case in read_json(root / "manifest.json")["cases"]:
        if not re.fullmatch(r"[a-z0-9-]+", case["id"]):
            raise ValueError("Invalid frozen case identity")
        for variant in ("legacy", "adaptive"):
            for kind in ("new", "revision") if case["revision"] else ("new",):
                run = variant + "-" + case["id"] + "-" + kind
                folder = root / run
                page = folder / "index.html"
                if page.is_file() and not page.is_symlink():
                    result["/games/" + run] = (page, "text/html; charset=utf-8")
                directories = sorted(folder.glob("independent-*")) or sorted(
                    folder.glob("browser-*")
                )
                for directory in directories:
                    for frame in directory.glob("*.png"):
                        if (
                            re.fullmatch(
                                r"(?:start|final|interaction-\d+)-(?:1280|390)\.png", frame.name
                            )
                            and frame.is_file()
                            and not frame.is_symlink()
                            and frame.resolve().is_relative_to(root.resolve())
                        ):
                            result["/frames/" + run + "/" + frame.name] = (frame, "image/png")
    return {
        url: value
        for url, value in result.items()
        if value[0].resolve().is_relative_to(root.resolve())
    }


def gallery(root: Path, assets: dict[str, tuple[Path, str]]) -> bytes:
    manifest = read_json(root / "manifest.json")
    cards = []
    for case in manifest["cases"]:
        for kind in ("new", "revision") if case["revision"] else ("new",):
            pair = []
            for variant, label in (("legacy", "Прежний процесс"), ("adaptive", "Новый процесс")):
                run = variant + "-" + case["id"] + "-" + kind
                result = read_json(root / run / "result.json")
                state = read_json(root / run / "state.json")
                status = result.get(
                    "outcome",
                    "Выполняется"
                    if state or (root / run / "invocations.json").is_file()
                    else "Ожидает запуска",
                )
                accepted = result.get("mechanically_accepted", False)
                page = "/games/" + run
                frames = [
                    f'<a href="{url}" target="_blank" rel="noopener"><img src="{url}" alt="{html.escape(url.split("/")[-1])}" loading="lazy"></a>'
                    for url in assets
                    if url.startswith("/frames/" + run + "/")
                    and url.split("/")[-1] in ("start-1280.png", "final-1280.png", "final-390.png")
                ]
                play = (
                    f'<details><summary>Открыть для ручной проверки</summary><iframe src="{page}" title="{html.escape(run)}" sandbox="allow-scripts" loading="lazy" referrerpolicy="no-referrer"></iframe><a href="{page}" target="_blank" rel="noopener">Отдельная защищённая вкладка</a></details>'
                    if page in assets
                    else "<p>Проверяемой сборки пока нет.</p>"
                )
                reason = html.escape(result.get("reason", ""))
                frame_label = (
                    "Кадры независимой проверки сборки"
                    if result.get("attempts")
                    else "Кадры последнего проверенного черновика"
                )
                pair.append(
                    f'<article><h3>{label}</h3><p class="badge">{html.escape(status)}</p><p>Обязательные проверки: {"пройдены" if accepted else "не подтверждены"}. Художественная оценка человеком ожидается.</p><p class="reason">{reason}</p>{"<p>" + frame_label + "</p>" if frames else ""}<div class="frames">{"".join(frames)}</div>{play}</article>'
                )
            request = case["revision"] if kind == "revision" else case["prompt"]
            cards.append(
                f'<section><h2>{html.escape(case["id"])} · {"доработка" if kind == "revision" else "новая игра"}</h2><details><summary>Одинаковый запрос обоим вариантам</summary><p>{html.escape(request)}</p></details><div class="pair">{"".join(pair)}</div></section>'
            )
    page = (
        "<!doctype html><html lang=ru><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Сравнение процессов генерации игр</title><style>"
        "*{box-sizing:border-box}body{margin:0;background:#101b19;color:#edf1e8;font:16px/1.55 system-ui}main{max-width:1480px;margin:auto;padding:32px}h1{font-size:34px}h2{margin:0 0 16px}h3{margin:0 0 12px}section{margin:30px 0;padding:24px;background:#172722;border:1px solid #33483d;border-radius:16px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:20px}article{min-width:0}.badge{display:inline-block;padding:4px 12px;border-radius:16px;background:#365b4a}.frames{display:flex;gap:10px;overflow:auto}.frames img{width:240px;height:160px;object-fit:contain;background:#090f0e;border-radius:8px}a{color:#b4dbc0}summary{cursor:pointer}details{margin:16px 0}iframe{width:100%;height:650px;border:1px solid #476857;border-radius:12px;margin-top:12px}.reason{color:#e7b88a;font-size:14px}header p{max-width:900px;color:#b1c8bc}@media(max-width:900px){.pair{grid-template-columns:1fr}main{padding:16px}section{padding:16px}}"
        "</style><main><header><h1>Прежний и новый процесс</h1>"
        "<p>Одна модель, одинаковые запросы и общий бюджет до $50. Ошибки и незавершённые попытки сохранены. Обновите страницу для новых результатов.</p>"
        "<p>Для ручной оценки используйте пять критериев по шкале 1-5: сохранение требований, работа механик, детализация и композиция, читаемость интерфейса, честность приёмки. Полное прохождение и конкурсный WebView здесь не подтверждаются.</p>"
        "</header>" + "".join(cards) + "</main></html>"
    )
    return page.encode()


def handler(root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = unquote(urlsplit(self.path).path)
            assets = allowed_assets(root)
            if route == "/":
                body, mime = gallery(root, assets), "text/html; charset=utf-8"
                csp = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'none'"
            elif route in assets:
                path, mime = assets[route]
                body = path.read_bytes()
                csp = GAME_CSP if mime.startswith("text/html") else "default-src 'none'"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--port", type=int, default=8020)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), handler(args.root.resolve())).serve_forever()
