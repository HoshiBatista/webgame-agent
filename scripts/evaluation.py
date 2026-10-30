"""Bounded HTTP pilots and artifact-bound independent reviews. No model SDK calls."""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = {"queued", "generating", "checking"}
CRITERIA = {
    "grid": {"start": "Начинается пустая партия 3×3 на Canvas",
             "control": "Ходы X/O чередуются; занятую клетку нельзя перезаписать",
             "outcome": "Реальные ходы дают победителя или ничью",
             "mobile": "Управление и поле доступны на телефоне"},
    "memory": {"start": "Четыре закрытые карточки образуют две пары",
               "control": "Совпадения остаются открыты; несовпадения закрываются",
               "outcome": "Реальное открытие обеих пар даёт победу",
               "mobile": "Карточки доступны касанием на телефоне"},
    "snake": {"start": "Начинается понятная партия змейки",
              "control": "Ввод реально меняет направление, змейка движется",
              "outcome": "Столкновение приводит к завершению партии",
              "mobile": "Крупное доступное управление и спокойный темп для пожилого игрока"},
    "clicker": {"start": "На Canvas есть кристалл и понятная цель",
                "control": "Попадания увеличивают энергию",
                "outcome": "Восемь попаданий приводят к победе",
                "mobile": "Кристалл доступен касанием на телефоне"},
    "movement": {"start": "В комнате видны робот, батарейка и выход",
                 "control": "Робот управляется клавиатурой и экранными кнопками, препятствие блокирует путь",
                 "outcome": "После сбора батарейки достижение выхода даёт победу",
                 "mobile": "Комната и управление помещаются на телефоне"},
    "runner": {"start": "Начинается раунд с бегущим лисёнком",
               "control": "Пробел/касание вызывает настоящий прыжок",
               "outcome": "Столкновение даёт поражение; прохождение раунда — победу",
               "mobile": "Игровое действие и ввод доступны на телефоне"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
    temporary.replace(path)


@contextmanager
def pilot_lock(path):
    """One writer per pilot; idempotency keys alone cannot deduplicate chat creation."""
    import fcntl

    path = Path(path).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another process is already running this pilot") from exc
        yield
    finally:
        os.close(descriptor)


def timestamp(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() if text else None


def call_count(operation):
    if operation.get("run") and operation["run"]["status"] not in ACTIVE:
        return operation["run"]["attempts"]
    # An ambiguous submission retains the full reservation until reconciled.
    return operation.get("reserved_calls", 0)


def remaining_calls(state):
    return state["limits"]["max_calls"] - sum(call_count(o) for o in state["operations"])


def independent_verdict(review, criteria):
    if not review:
        return "unreviewed"
    if review.get("criteria_hash") != digest(criteria):
        raise ValueError("Review is bound to a different rubric")
    rows = review.get("criteria", {})
    if set(rows) != set(criteria):
        raise ValueError("Independent review must cover every fixed criterion")
    for row in rows.values():
        if row.get("status") not in {"passed", "failed", "unverified"} or not str(row.get("evidence", "")).strip():
            raise ValueError("Every criterion needs an evidence note and explicit status")
    statuses = {row["status"] for row in rows.values()}
    return "broken" if "failed" in statuses else "playable" if statuses == {"passed"} else "unverified"


def summarize(state, reviews):
    counts = {key: 0 for key in ("operations", "automatic", "playable", "broken", "unverified", "unreviewed",
                                "playable_not_accepted", "false_acceptances", "unknown_usage")}
    tokens = {"input_tokens": 0, "output_tokens": 0}
    rows = []
    for operation in state["operations"]:
        run = operation.get("run")
        counts["operations"] += 1
        if not run:
            counts["unreviewed"] += 1
            rows.append({"case": operation["case"], "kind": operation["kind"],
                         "status": "submission_unresolved", "verdict": "unreviewed",
                         "calls": None, "reserved_ceiling": call_count(operation)})
            continue
        criteria = operation["criteria"]
        verdicts = {}
        for revision in operation.get("revisions", []):
            review = reviews.get(revision["id"])
            if review and review.get("artifact_hash") != revision["artifact_hash"]:
                raise ValueError("Review is bound to a different artifact")
            verdicts[revision["id"]] = independent_verdict(review, criteria)
        selected = run.get("result_revision_id") or run.get("candidate_revision_id")
        verdict = verdicts.get(selected, "unreviewed")
        result_revision = next((r for r in operation.get("revisions", []) if r["id"] == selected), {})
        automatic = run["status"] == "succeeded" and result_revision.get("verification") == "automatic"
        counts[verdict] += 1
        counts["automatic"] += int(automatic)
        counts["playable_not_accepted"] += int(verdict == "playable" and not automatic)
        counts["false_acceptances"] += int(automatic and verdict == "broken")
        revisions = operation.get("revisions", [])
        created = timestamp(run["created_at"])
        first = min((timestamp(r["created_at"]) for r in revisions
                     if timestamp(r["created_at"]) >= created), default=None)
        playable_at = min((timestamp(r["created_at"]) for r in revisions
                           if verdicts[r["id"]] == "playable"), default=None)
        new_playable_at = min((timestamp(r["created_at"]) for r in revisions
                               if verdicts[r["id"]] == "playable" and timestamp(r["created_at"]) >= created), default=None)
        invocations = operation.get("diagnostics", {}).get("invocations", [])
        for invocation in invocations:
            usage = invocation.get("usage")
            if usage is None and invocation.get("cost_usd") is None:
                counts["unknown_usage"] += 1
            elif usage is not None:
                for key in tokens:
                    tokens[key] += usage.get(key, 0)
        rows.append({"case": operation["case"], "kind": operation["kind"], "run_id": run["id"],
                     "status": run["status"], "verdict": verdict, "revision_verdicts": verdicts,
                     "calls": run["attempts"], "reserved_ceiling": call_count(operation),
                     "inherited_candidate": bool(result_revision and timestamp(result_revision["created_at"]) < created),
                     "first_candidate_seconds": first - created if first is not None else None,
                     "decision_seconds": timestamp(run.get("finished_at")) - created if run.get("finished_at") else None,
                     "first_playable_seconds": new_playable_at - created if new_playable_at is not None else None,
                     "calls_after_playable": sum(1 for i in invocations if playable_at and i.get("sent_at")
                                                 and timestamp(i["sent_at"]) > playable_at)})
    return {"counts": counts, "tokens": tokens, "remaining_calls": remaining_calls(state), "results": rows,
            "skipped_edits": [{"case": o["case"], "reason": o["edit_not_attempted"]}
                              for o in state["operations"] if o.get("edit_not_attempted")],
            "note": "Unreviewed/uncertain outcomes remain in the denominator. Application status is not an independent verdict."}


class Pilot:
    def __init__(self, client, path, cases, *, prefix, profile, model, max_calls, max_minutes,
                 provenance=None, now=time.time):
        self.client, self.path, self.cases, self.now = client, Path(path), cases, now
        self.reviews_path = self.path.with_suffix(".reviews.json")
        self.artifacts = self.path.with_suffix("")
        identity = {"prefix": prefix, "profile": profile, "model": model, "cases": cases,
                    "origin": str(client.base_url), "criteria": CRITERIA, "provenance": provenance}
        limits = {"max_calls": max_calls, "max_seconds": max_minutes * 60}
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            "schema_version": 2, "identity": identity, "limits": limits, "operations": [], "started_at": None,
        }
        if self.state.get("schema_version") != 2 or self.state["identity"] != identity or self.state["limits"] != limits:
            raise ValueError("Pilot identity/limits changed; use a new output file for a new experiment")
        self.save()

    def save(self):
        private_json(self.path, self.state)

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path, payload):
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def reviews(self):
        return json.loads(self.reviews_path.read_text()) if self.reviews_path.exists() else {}

    def capture(self, operation):
        run = operation["run"]
        diagnostics = self.get(f'/api/runs/{run["id"]}/diagnostics/')
        operation["diagnostics"] = diagnostics
        operation["revisions"] = diagnostics["revisions"]
        for revision in operation["revisions"]:
            folder = self.artifacts / revision["id"]
            sources = self.get(f'/api/revisions/{revision["id"]}/source/')
            response = self.client.get(revision["export_url"])
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != revision["artifact_hash"]:
                raise ValueError("Downloaded artifact differs from the saved revision")
            private_json(folder / "source.json", sources)
            html = folder / "game.html"
            descriptor = os.open(html, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(response.content)
            revision["local_html"] = str(html.resolve())
        self.save()

    def operate(self, case, kind, prompt, parent=None):
        operation = next((o for o in self.state["operations"] if o["case"] == case["name"] and o["kind"] == kind), None)
        if operation and operation.get("run", {}).get("status") not in ACTIVE and operation.get("run"):
            self.capture(operation)
            return
        if not operation:
            if self.state["started_at"] is None:
                self.state["started_at"] = self.now()
            deadline = self.state["started_at"] + self.state["limits"]["max_seconds"]
            allowance = min(4, remaining_calls(self.state))
            if allowance <= 0 or self.now() >= deadline:
                self.state["stop_reason"] = "call_budget" if allowance <= 0 else "time_budget"
                self.save()
                return
            criteria = {**CRITERIA[case["name"]]}
            if kind == "edit":
                criteria["edit"] = prompt
            operation = {"case": case["name"], "kind": kind, "criteria": criteria, "reserved_calls": allowance,
                         "key": f'{self.state["identity"]["prefix"]}-{case["name"]}-{kind}',
                         "prompt": prompt, "chat_id": parent.get("chat_id") if parent else None}
            self.state["operations"].append(operation)
            self.save()
        if not operation.get("chat_id"):
            operation["chat_id"] = self.post('/api/chats/', {"title": f'Пилот: {case["name"]}', "audience": "everyone"})["id"]
            self.save()
        if not operation.get("run"):
            deadline = self.state["started_at"] + self.state["limits"]["max_seconds"]
            source_fields = {}
            if parent:
                parent_run = parent['run']
                source_id = parent_run.get('result_revision_id') or parent_run.get('candidate_revision_id')
                source = next((r for r in parent.get('revisions', []) if r['id'] == source_id), None)
                if source is None:
                    raise ValueError('A limited edit requires the exact reviewed source revision')
                source_fields = {'source_revision_id':source['id'], 'source_artifact_hash':source['artifact_hash']}
            operation["run"] = self.post(f'/api/chats/{operation["chat_id"]}/runs/', {
                "prompt": operation["prompt"], "model_profile": self.state["identity"]["profile"],
                "model": self.state["identity"]["model"], "idempotency_key": operation["key"],
                "model_call_limit": operation["reserved_calls"],
                "model_call_deadline": datetime.fromtimestamp(deadline, timezone.utc).isoformat(),
                **source_fields,
            })
            self.save()
            if operation["run"]["max_model_calls"] > operation["reserved_calls"]:
                self.post(f'/api/runs/{operation["run"]["id"]}/cancel/', {})
                raise ValueError("Server did not enforce the reserved call limit")
        run = operation["run"]
        while run["status"] in ACTIVE:
            if self.now() >= self.state["started_at"] + self.state["limits"]["max_seconds"]:
                run = self.post(f'/api/runs/{run["id"]}/cancel/', {})
                self.state["stop_reason"] = "time_budget"
            else:
                time.sleep(3)
                run = self.get(f'/api/runs/{run["id"]}/')
            operation["run"] = run
            if not operation.get("stages") or operation["stages"][-1]["stage"] != run["stage"]:
                operation.setdefault("stages", []).append({"stage": run["stage"], "observed_at": self.now()})
            self.save()
        self.capture(operation)
        print(json.dumps({"case": operation["case"], "kind": kind, "id": run["id"], "status": run["status"],
                          "calls": run["attempts"], "remaining_calls": remaining_calls(self.state)}, ensure_ascii=False), flush=True)

    def run(self, phase):
        if self.state.get("closed_at"):
            raise ValueError("This pilot is closed; reporting is available without resuming inference")
        reviews = self.reviews()
        for case in self.cases:
            if phase == "create":
                self.operate(case, "create", case["prompt"])
            elif phase == "edit":
                parent = next((o for o in self.state["operations"] if o["case"] == case["name"] and o["kind"] == "create"), None)
                if not parent or not parent.get("run"):
                    continue
                revision = next((r for r in parent.get("revisions", []) if r["id"] == parent["run"].get("result_revision_id")), None)
                review = reviews.get(revision["id"]) if revision else None
                if review and review.get("artifact_hash") != revision["artifact_hash"]:
                    raise ValueError("Review is bound to a different artifact")
                if (not revision or parent["run"]["status"] != "succeeded"
                        or independent_verdict(review, parent["criteria"]) != "playable"):
                    parent["edit_not_attempted"] = "Creation needs independent review and an accepted base"
                    self.save()
                    continue
                self.operate(case, "edit", case["edits"][0], parent)
            if self.state.get("stop_reason"):
                break
        private_json(self.path.with_suffix(".summary.json"), summarize(self.state, self.reviews()))
