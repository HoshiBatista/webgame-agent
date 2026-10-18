"""Explicit paid HTTP pilot; persists each ID before waiting, never silently retries a run.

Use only with an approved app-wide budget. Credentials stay in .env, results contain no cookies.
"""

import argparse
import json
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

CASES = [
    {
        "name": "grid",
        "prompt": "Красивая мини-игра крестики-нолики на двоих по очереди на одном экране, поле 3 на 3. Рисуй поле и символы на Canvas. Понятное начало и объявление победителя или ничьей, управление касанием и мышью.",
        "edits": ["Поменяй цвет крестиков на коралловый, а ноликов на бирюзовый. Остальную игру сохрани.", "Увеличь кнопку начала игры на 15 процентов, остальное сохрани."],
    },
    {
        "name": "memory",
        "prompt": "Сделай красивую маленькую игру на память: четыре закрытые карточки, две пары фруктов. Касанием открываем две карточки, одинаковые остаются открытыми, разные закрываются. Когда обе пары найдены — победа. Canvas, телефон и мышь, понятное начало.",
        "edits": ["Сделай рубашки карточек тёмно-фиолетовыми с золотым узором. Механику сохрани.", "Добавь короткую видимую надпись «Пара найдена!» при совпадении карточек."],
    },
    {
        "name": "clicker",
        "prompt": "Сделай красивую мини-игру: касаниями большого кристалла в центре Canvas накопить 8 единиц энергии, затем победа. Кристалл красиво светится и реагирует на касания. Понятное начало, прогресс и цель, телефон и мышь.",
        "edits": ["Перекрась кристалл из текущего цвета в янтарный, больше ничего не меняй.", "Добавь второй короткий уровень с целью 10 единиц энергии после первого. Сохрани управление и стиль."],
    },
    {
        "name": "movement",
        "prompt": "Сделай мини-игру на Canvas: маленький робот собирает одну батарейку и достигает выхода в красивой комнате. Движение стрелками на клавиатуре и экранными стрелками на телефоне. Комната без лабиринта, одно препятствие, короткий путь, понятное начало и победа у выхода после сбора батарейки.",
        "edits": ["Сделай корпус робота жёлтым и добавь красивую тень. Механику сохрани.", "Увеличь скорость робота на 10 процентов, сохрани столкновение с препятствием и управление."],
    },
    {
        "name": "runner",
        "prompt": "Сделай красивый короткий Canvas-раннер: лисёнок сам бежит по лесу, касанием или пробелом прыгает через пень. Небольшой раунд на 6 секунд, столкновение означает поражение, дойти до конца — победа. Понятное начало, телефон и клавиатура.",
        "edits": ["Сделай фон леса осенним, механику сохрани.", "Увеличь высоту прыжка на 10 процентов, остальное сохрани."],
    },
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--origin", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", default="grid,memory,clicker,movement,runner")
    args = parser.parse_args()
    destination = Path(args.output)
    state = json.loads(destination.read_text()) if destination.exists() else {
        "model": args.model, "prefix": args.prefix, "cases": [], "started_at": time.time()
    }

    def save():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        temporary.replace(destination)

    credentials = dotenv_values(".env")
    client = httpx.Client(base_url=args.origin, timeout=30)
    session = client.get("/api/session/").json()
    client.headers["X-CSRFToken"] = session["csrfToken"]
    login = client.post("/api/login/", json={
        "username": credentials["DJANGO_SUPERUSER_USERNAME"],
        "password": credentials["DJANGO_SUPERUSER_PASSWORD"],
    })
    login.raise_for_status()
    client.headers["X-CSRFToken"] = login.json()["csrfToken"]
    state.setdefault("budget_before", login.json()["budget"])

    for case in CASES:
        if case["name"] not in args.cases.split(","):
            continue
        item = next((c for c in state["cases"] if c["name"] == case["name"]), None)
        if item is None:
            response = client.post("/api/chats/", json={"title": "", "audience": "everyone"})
            response.raise_for_status()
            item = {**case, "chat_id": response.json()["id"], "runs": []}
            state["cases"].append(item)
            save()
        for index, prompt in enumerate([case["prompt"], *case["edits"]]):
            if index > 0 and item["runs"][index - 1]["status"] != "succeeded":
                item["remaining_edits"] = "not attempted: previous operation not automatically accepted"
                save()
                break
            if len(item["runs"]) <= index:
                response = client.post(f'/api/chats/{item["chat_id"]}/runs/', json={
                    "prompt": prompt, "model": args.model,
                    "idempotency_key": f"{args.prefix}-{case['name']}-{index}",
                })
                response.raise_for_status()
                item["runs"].append(response.json())
                save()
            run = item["runs"][index]
            while run["status"] in {"queued", "generating", "checking"}:
                time.sleep(3)
                response = client.get(f'/api/runs/{run["id"]}/')
                response.raise_for_status()
                run = response.json()
                item["runs"][index] = run
                save()
            print(json.dumps({"case": case["name"], "step": index, "id": run["id"],
                              "status": run["status"], "metrics": run["metrics"],
                              "error": (run.get("error") or {}).get("code")}), flush=True)
    state["budget_after"] = client.get("/api/session/").json()["budget"]
    state["finished_at"] = time.time()
    save()


if __name__ == "__main__":
    main()
