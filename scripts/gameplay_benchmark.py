"""Replay independent, artifact-bound game checks through the isolated validator."""

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation import digest, private_json  # noqa: E402

DEFAULT_SUITE = ROOT / "benchmarks/gameplay/suite.json"


def load_cases(path):
    manifest = json.loads(path.read_text())
    if manifest["version"] != 1 or not manifest["cases"]:
        raise ValueError("Expected a nonempty version 1 gameplay suite")
    cases = []
    names = set()
    for row in manifest["cases"]:
        artifact_hash = row["artifact_hash"]
        if row["case"] in names or (artifact_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", artifact_hash)):
            raise ValueError("Repeated case or invalid artifact hash")
        names.add(row["case"])
        row["run_id"] = str(UUID(row["run_id"]))
        if artifact_hash is None:
            cases.append({**row, "checks": []})
            continue
        checks = json.loads((path.parent / row["checks"]).read_text())
        if not checks or len({c["id"] for c in checks}) != len(checks):
            raise ValueError("Each game needs independent checks with unique IDs")
        if not {"start", "control", "outcome"} <= {c["category"] for c in checks}:
            raise ValueError("Each game must check start, controls and outcome")
        cases.append({**row, "checks": checks})
    return cases


def creation_metrics(run):
    from studio.models import Invocation, Run

    # A benchmark chat belongs to a single test game. Include failed and abandoned
    # attempts through this revision, including their receipts, once per invocation.
    runs = Run.objects.filter(chat_id=run.chat_id, created_at__lte=run.created_at)
    intervals = list(runs.values_list("created_at", "finished_at"))
    if any(finished is None for _, finished in intervals):
        raise ValueError("A benchmark game still has an unfinished run")
    receipts = Invocation.objects.filter(run__in=runs).values_list(
        "request__operation", "sent_at", "state", "cost_usd", "reservation_usd"
    )
    return {
        "runs": len(intervals),
        "generation_seconds": round(sum((end - start).total_seconds() for start, end in intervals), 3),
        **invocation_metrics(receipts),
    }


def invocation_metrics(receipts):
    ops: Counter[str] = Counter()
    unpriced = unknown = 0
    known_cost = reserve = Decimal(0)
    for op, sent_at, state, cost, reservation in receipts:
        if sent_at is not None:
            ops[op] += 1
        # Historical receipts can carry a cost or an unresolved reserve even without sent_at.
        if cost is not None:
            known_cost += cost
        if state == "unknown":
            unknown += 1
            reserve += reservation
        elif sent_at is not None and cost is None:
            unpriced += 1
    return {
        "model_operations": dict(ops),
        "repair_calls": sum(ops[k] for k in ("repair", "check_repair", "visual_patch")),
        "edit_calls": ops["edit"],
        "known_cost_usd": str(known_cost),
        "unknown_calls": unknown,
        "unknown_reserved_usd": str(reserve),
        "other_calls_without_cost": unpriced,
    }


def export_cases(cases, directory):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gameforge.settings")
    import django

    django.setup()
    from studio.models import Run

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    chats = set()
    for case in cases:
        run = Run.objects.get(pk=case["run_id"])
        if run.chat_id in chats:
            raise ValueError("Each case needs its own benchmark chat to avoid double counting generation receipts")
        chats.add(run.chat_id)
        version = run.result_revision or run.candidate_revision
        expected = case["artifact_hash"]
        if case["profile"] != run.model_profile or expected != (version.artifact_hash if version else None):
            raise ValueError(f"Run, profile or revision mismatch for {case['case']}")
        if version and hashlib.sha256(version.html.encode()).hexdigest() != expected:
            raise ValueError("Saved export failed its hash check")
        # Source and provenance travel together. Include no model requests or account information.
        private_json(directory / (case["run_id"] + ".json"), {
            "html": version.html if version else None, "run_id": str(run.id),
            "revision_id": str(version.id) if version else None,
            "profile": run.model_profile, "metrics": creation_metrics(run),
        })


def run_case(case, directory):
    from validation.criteria import OperatorCriterion
    from validation.service import validate

    expected = case["artifact_hash"]
    checks = case["checks"]
    row = {key: case[key] for key in ("case", "family", "profile", "run_id", "artifact_hash", "seed", "clock")}
    row.update(checks_digest=digest(checks), checks_total=len(checks), checks_passed=0)
    path = directory / (case["run_id"] + ".json")
    if not path.exists():
        return {**row, "status": "missing_artifact"}
    try:
        pack = json.loads(path.read_bytes())
        if pack["run_id"] != case["run_id"] or pack["profile"] != case["profile"]:
            return {**row, "status": "artifact_mismatch"}
        generation = pack["metrics"]
        generation_totals([generation])
        revision_id = pack["revision_id"]
        if expected is None and pack["html"] is None and revision_id is None:
            return {**row, "status": "no_revision", "generation": generation}
        if not isinstance(pack["html"], str) or hashlib.sha256(pack["html"].encode()).hexdigest() != expected:
            return {**row, "status": "artifact_mismatch"}
    except (ValueError, TypeError, ArithmeticError, KeyError, UnicodeError):
        return {**row, "status": "invalid_pack"}
    result = validate(pack["html"], checks, artifact_hash=expected,
                      test_profile={"seed": case["seed"], "clock": case["clock"]},
                      operator_criteria=tuple(OperatorCriterion.for_check(c) for c in checks))
    return {**row, "revision_id": revision_id, "generation": generation,
            "status": result["status"], "replay_seconds": result["elapsed_seconds"],
            "environment": result.get("environment"), "checks_passed": sum(
                f["status"] == "passed" for f in result["facts"]),
            "findings": [{"code": f["code"], "check": f.get("check_id")} for f in result["findings"]]}


def generation_totals(metrics):
    return {"measured_games": len(metrics),
            "generation_seconds": round(sum(m["generation_seconds"] for m in metrics), 3),
            "repair_calls": sum(m["repair_calls"] for m in metrics),
            "edit_calls": sum(m["edit_calls"] for m in metrics),
            "known_cost_usd": str(sum((Decimal(m["known_cost_usd"]) for m in metrics), Decimal(0))),
            "unknown_calls": sum(m["unknown_calls"] for m in metrics),
            "unknown_reserved_usd": str(sum((Decimal(m["unknown_reserved_usd"]) for m in metrics), Decimal(0))),
            "other_calls_without_cost": sum(m["other_calls_without_cost"] for m in metrics)}


def summarize(rows):
    statuses = Counter(row["status"] for row in rows)
    passed = statuses["passed"]
    return {"scheduled": len(rows), "passed": passed,
            "passed_fraction": round(passed / len(rows), 4), "statuses": dict(statuses),
            "checks_passed": sum(row["checks_passed"] for row in rows),
            "checks_total": sum(row["checks_total"] for row in rows),
            **generation_totals([row["generation"] for row in rows if "generation" in row])}


def comparison_rows(report, profile):
    result = {}
    for row in report["cases"]:
        if profile and row["profile"] != profile:
            continue
        key = row["family"] if profile else row["case"]
        if key in result:
            raise ValueError(f"Ambiguous comparison group {key!r}; select one game per family and profile")
        result[key] = row
    if not result:
        raise ValueError("Report contains no cases for this profile")
    return result


def compare(before, after, before_profile=None, after_profile=None):
    if bool(before_profile) != bool(after_profile):
        raise ValueError("Set both profiles to compare results by family")
    left = comparison_rows(before, before_profile)
    right = comparison_rows(after, after_profile)
    pairs = []
    for name in sorted(left.keys() & right.keys()):
        a, b = left[name], right[name]
        baseline, current = summarize([a]), summarize([b])
        delta = None
        if baseline["measured_games"] and current["measured_games"]:
            delta = {"generation_seconds": round(current["generation_seconds"] - baseline["generation_seconds"], 3),
                     "repair_calls": current["repair_calls"] - baseline["repair_calls"],
                     "edit_calls": current["edit_calls"] - baseline["edit_calls"],
                     "known_cost_usd": str(Decimal(current["known_cost_usd"]) - Decimal(baseline["known_cost_usd"]))}
        pairs.append({"group": name, "before_case": a["case"], "after_case": b["case"],
                      "same_artifact": a["artifact_hash"] == b["artifact_hash"],
                      "same_checks": a["checks_digest"] == b["checks_digest"],
                      "same_environment": bool(a.get("environment")) and a.get("environment") == b.get("environment"),
                      "same_clock_and_seed": (a["clock"], a["seed"]) == (b["clock"], b["seed"]),
                      "before": baseline, "after": current, "generation_delta": delta})
    return {"pairs": pairs, "only_before": sorted(left.keys() - right.keys()),
            "only_after": sorted(right.keys() - left.keys())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
        sub.add_argument("--pack", required=True, type=Path)
        sub.add_argument("--case", action="append", help="Run/export only the named case (repeatable)")
        if command == "run":
            sub.add_argument("--report", required=True, type=Path)
    diff = commands.add_parser("compare")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--before-profile")
    diff.add_argument("--after-profile")
    args = parser.parse_args()
    if args.command == "compare":
        result = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()),
                         args.before_profile, args.after_profile)
        print(json.dumps(result, indent=2))
        return 0
    cases = load_cases(args.suite)
    if args.case:
        missing = set(args.case) - {c["case"] for c in cases}
        if missing:
            parser.error("Unknown cases: " + ", ".join(sorted(missing)))
        cases = [c for c in cases if c["case"] in args.case]
    if args.command == "export":
        export_cases(cases, args.pack)
        return 0
    # Default to the local OS sandbox, or explicitly select the isolated Docker service.
    os.environ.setdefault("VALIDATOR_BACKEND", "native")
    rows = []
    for case in cases:
        row = run_case(case, args.pack)
        rows.append(row)
        print(f"{row['case']} {row['status']} {row['checks_passed']}/{row['checks_total']}", flush=True)
    summary = summarize(rows)
    private_json(args.report, {"version": 1, "suite_digest": digest(cases), "cases": rows, "summary": summary,
                               "profiles": {p: summarize([r for r in rows if r["profile"] == p])
                                            for p in sorted({r["profile"] for r in rows})}})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(summary["passed"] != summary["scheduled"])


if __name__ == "__main__":
    raise SystemExit(main())
