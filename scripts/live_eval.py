"""Explicit paid HTTP pilot; persists each ID before waiting, never silently retries a run.

Use only with an approved app-wide budget. Credentials stay in .env, results contain no cookies.
"""

import argparse
import hashlib
import json
from pathlib import Path

import httpx
from dotenv import dotenv_values

if __package__:
    from scripts.evaluation import Pilot, pilot_lock, private_json, summarize
else:
    from evaluation import Pilot, pilot_lock, private_json, summarize

CASES = [
    {
        "name": "snake",
        "prompt": "замути змейку для бабушки",
        "edits": ["Сделай змейку фиолетовой. Остальную игру и её темп сохрани."],
    },
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


def provenance():
    paths = [*Path("generation").rglob("*.py"), *Path("validation").rglob("*.py"),
             *[Path("studio") / name for name in ("tasks.py", "services.py", "models.py", "acceptance.py",
                                                   "continuations.py", "serialization.py", "recovery.py", "views.py",
                                                   "check_repair.py")],
             Path("scripts/live_eval.py"), Path("scripts/evaluation.py")]
    return {"source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
            "weight_revision": "Not exposed by the relay API; model alias only",
            "sampling_defaults": "Provider defaults; inspect captured request for explicit values"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=["prepare", "create", "edit", "report"], required=True)
    parser.add_argument("--prefix")
    parser.add_argument("--model")
    parser.add_argument("--model-profile", choices=["lite", "pro"], default="lite")
    parser.add_argument("--origin", default="http://127.0.0.1:8000")
    parser.add_argument("--cases", default="grid,snake,memory")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--max-minutes", type=int)
    args = parser.parse_args()
    destination = Path(args.output)
    if args.phase == "report":
        state = json.loads(destination.read_text())
        review_path = destination.with_suffix(".reviews.json")
        summary = summarize(state, json.loads(review_path.read_text()) if review_path.exists() else {})
        private_json(destination.with_suffix(".summary.json"), summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if (not args.prefix or len(args.prefix) > 70 or not args.max_calls or args.max_calls < 1
            or not args.max_minutes or args.max_minutes < 1):
        parser.error("Provide an explicit approved prefix, --max-calls and --max-minutes")
    names = args.cases.split(",")
    cases = [next((c for c in CASES if c["name"] == name), None) for name in names]
    if any(c is None for c in cases) or len(set(names)) != len(names):
        parser.error("Unknown or repeated case")
    credentials = dotenv_values(".env")
    with pilot_lock(destination), httpx.Client(base_url=args.origin, timeout=30) as client:
        session = client.get("/api/session/")
        session.raise_for_status()
        client.headers["X-CSRFToken"] = session.json()["csrfToken"]
        login = client.post("/api/login/", json={
            "username": credentials["DJANGO_SUPERUSER_USERNAME"],
            "password": credentials["DJANGO_SUPERUSER_PASSWORD"],
        })
        login.raise_for_status()
        client.headers["X-CSRFToken"] = login.json()["csrfToken"]
        profile = next(p for p in login.json()["capabilities"]["model_profiles"] if p["id"] == args.model_profile)
        if not profile["available"] or (args.model and args.model != profile["model"]):
            raise ValueError("Requested model profile is unavailable or does not match the model")
        pilot = Pilot(client, destination, cases, prefix=args.prefix, profile=args.model_profile,
                      model=profile["model"], max_calls=args.max_calls, max_minutes=args.max_minutes,
                      provenance=provenance())
        pilot.state.setdefault("profile", profile)
        pilot.state.setdefault("budget_before", login.json()["budget"])
        pilot.save()
        if args.phase != "prepare":
            pilot.run(args.phase)
            pilot.state["budget_after"] = pilot.get("/api/session/")["budget"]
            pilot.save()
        print(json.dumps({"phase": args.phase, "profile": profile, "output": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
