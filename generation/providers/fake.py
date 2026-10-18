"""A labelled fixture for infrastructure tests, never advertised as model generation."""

from copy import deepcopy

from ..artifacts import sha256
from ..errors import GenerationError

FIXTURE_FILES = {
    "index.html": '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Тестовая сцена</title><link rel="stylesheet" href="styles.css"><body><h1>Тестовая сцена — заглушка</h1><p id="status">Нажмите круг трижды</p><canvas id="arena" width="300" height="300" tabindex="0"></canvas><script src="game.js"></script></body></html>',
    "styles.css": "body{margin:0;background:#eff4ff;color:#183052;font:18px system-ui;text-align:center}canvas{max-width:100%;touch-action:none;border-radius:20px;background:#d9e4ff}h1{font-size:24px}",
    "game.js": 'window.gameState={hits:0};const board=document.querySelector("#arena");const ctx=board.getContext("2d");function draw(){ctx.clearRect(0,0,300,300);ctx.fillStyle="#5879e8";ctx.beginPath();ctx.arc(150,150,60,0,Math.PI*2);ctx.fill();ctx.fillStyle="white";ctx.font="32px sans-serif";ctx.fillText(String(gameState.hits),140,160)}function hit(){if(gameState.hits>=3)return;gameState.hits++;document.querySelector("#status").textContent=gameState.hits>=3?"Победа!":"Попаданий: "+gameState.hits;draw()}board.addEventListener("pointerdown",event=>{const r=board.getBoundingClientRect();const x=(event.clientX-r.left)*300/r.width;const y=(event.clientY-r.top)*300/r.height;if(Math.hypot(x-150,y-150)<60)hit()});board.addEventListener("keydown",event=>{if(event.code==="Space"){event.preventDefault();hit()}});draw();',
}


def fixture_response():
    tap = {"action": "tap", "selector": "#arena", "x": 150, "y": 150}
    return {
        "status": "ok",
        "operation": "create",
        "title": "Тестовая сцена — заглушка",
        "message": "Это fixture, модель не вызывалась.",
        "design": {
            "summary": "Три реальных попадания завершают тестовую сцену.",
            "visual": "Синий круг на светлом фоне.",
            "controls": ["Коснитесь круга", "Пробел при фокусе сцены"],
            "outcome": "Три попадания: победа.",
        },
        "base_revision": None,
        "files": [{"path": p, "content": c} for p, c in FIXTURE_FILES.items()],
        "patches": [],
        "checks": [
            {
                "id": "start",
                "category": "start",
                "requirement": "Видна понятная инструкция начала игры",
                "viewport": "mobile",
                "steps": [],
                "observation": {"source": "text", "selector": "#status"},
                "expect": {"operator": "contains", "value": "Нажмите"},
            },
            {
                "id": "tap",
                "category": "control",
                "requirement": "Реальное попадание увеличивает число попаданий",
                "viewport": "mobile",
                "steps": [tap],
                "observation": {"source": "state", "path": "gameState.hits"},
                "expect": {"operator": "eq", "value": 1},
            },
            {
                "id": "outcome",
                "category": "outcome",
                "requirement": "Три попадания приводят к победе",
                "viewport": "mobile",
                "steps": [deepcopy(tap) for _ in range(3)],
                "observation": {"source": "text", "selector": "#status"},
                "expect": {"operator": "eq", "value": "Победа!"},
            },
        ],
    }


def generate(request, *, on_event, is_cancelled):
    if is_cancelled():
        raise GenerationError(
            "cancelled",
            "Запуск отменён до запроса.",
            usage={"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0},
        )
    response = fixture_response()
    if request.get("files"):
        files = request["files"]
        response.update(
            operation=request.get("operation", "edit"),
            base_revision=str(request["base_revision"]),
            files=[],
            checks=request.get("checks") or response["checks"],
        )
        old = "#eff4ff" if "#eff4ff" in files["styles.css"] else "#fff5e8"
        response["patches"] = [
            {
                "path": "styles.css",
                "file_hash": sha256(files["styles.css"]),
                "old_text": old,
                "new_text": "#fff5e8" if old == "#eff4ff" else "#eff4ff",
            }
        ]
    on_event({"type": "provider", "message": "Тестовая заглушка; платного вызова нет."})
    return {"response": response, "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}}
