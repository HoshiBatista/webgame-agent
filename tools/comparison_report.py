"""Read-only measurement of a frozen comparison; human scores are never inferred."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def summarize(root: Path, ratings: dict | None = None) -> dict:
    manifest = load(root / "manifest.json")
    ledger = load(root / manifest.get("shared_ledger", "budget-ledger.json"))
    ratings = ratings or {}
    runs = []
    for case in manifest["cases"]:
        for revision in (False, True) if case["revision"] else (False,):
            for variant in ("legacy", "adaptive"):
                name = variant + "-" + case["id"] + ("-revision" if revision else "-new")
                folder = root / name
                result, state = load(folder / "result.json"), load(folder / "state.json")
                prefix = manifest.get("ledger_namespace", "") + name + ":"
                records = [r for k, r in ledger.items() if k.startswith(prefix)]
                usage = [r["usage"] for r in records if r.get("usage")]
                upper = sum(r.get("upper_nano", 0) for r in records) / 1e9
                reserved = sum(r.get("reserved_nano", 0) for r in records) / 1e9
                roles = {}
                for role in sorted({r.get("operation", "unknown") for r in records}):
                    selected = [r for r in records if r.get("operation", "unknown") == role]
                    role_usage = [r["usage"] for r in selected if r.get("usage")]
                    roles[role] = {
                        "paid_calls": sum(u.get("calls", 0) for u in role_usage),
                        "cost_upper_usd": sum(r.get("upper_nano", 0) for r in selected) / 1e9,
                        "reserved_usd": sum(r.get("reserved_nano", 0) for r in selected) / 1e9,
                        "input_tokens": sum(u.get("input_tokens", 0) for u in role_usage),
                        "cached_input_tokens": sum(
                            u.get("cached_input_tokens", 0) for u in role_usage
                        ),
                        "output_tokens": sum(u.get("output_tokens", 0) for u in role_usage),
                    }
                controller = state.get("draft", {}).get("adaptive", {})
                score = ratings.get("runs", {}).get(name)
                if score is not None and (
                    not ratings.get("reviewer")
                    or not ratings.get("reviewed_at")
                    or not isinstance(score, list)
                    or len(score) != len(case["rubric"])
                    or any(type(s) is not int or s < 1 or s > 5 for s in score)
                ):
                    raise ValueError("Human ratings require reviewer, date and five integer scores")
                runs.append(
                    {
                        "run": name,
                        "case": case["id"],
                        "variant": variant,
                        "revision": revision,
                        "outcome": result.get(
                            "outcome",
                            "running"
                            if state or (folder / "invocations.json").is_file()
                            else "not_started",
                        ),
                        "reason": result.get("reason", ""),
                        "mechanically_accepted": result.get("mechanically_accepted", False),
                        "visual_status": result.get("visual_status", "not_performed"),
                        "human_scores": score,
                        "cost_upper_usd": upper,
                        "reserved_usd": reserved,
                        "paid_calls": sum(u.get("calls", 0) for u in usage),
                        "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
                        "cached_input_tokens": sum(u.get("cached_input_tokens", 0) for u in usage),
                        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
                        "elapsed_seconds": result.get("elapsed_seconds"),
                        "attempts": result.get("attempts"),
                        "source_kept": result.get("source_kept"),
                        "roles": roles,
                        "supervisor_decisions": len(controller.get("decisions", [])),
                        "measured_progress_observations": sum(
                            o.get("progress") == "measured"
                            for o in controller.get("observations", [])
                        ),
                        "current_repeated_failure_types": sum(
                            s.get("repeats", 0) >= 3 for s in controller.get("stall", {}).values()
                        ),
                    }
                )
    by_variant = {}
    for variant in ("legacy", "adaptive"):
        selected = [r for r in runs if r["variant"] == variant]
        accepted = [r for r in selected if r["mechanically_accepted"]]
        by_variant[variant] = {
            "new_games_accepted": sum(not r["revision"] for r in accepted),
            "revisions_accepted": sum(r["revision"] for r in accepted),
            "cost_upper_usd": sum(r["cost_upper_usd"] for r in selected),
            "mean_accepted_cost_usd": sum(r["cost_upper_usd"] for r in accepted) / len(accepted)
            if accepted
            else None,
        }
    pairs = []
    for current in (r for r in runs if r["variant"] == "adaptive"):
        old = next(
            r
            for r in runs
            if r["variant"] == "legacy"
            and r["case"] == current["case"]
            and r["revision"] == current["revision"]
        )
        if current["human_scores"] and old["human_scores"]:
            # The frozen visual rubric is its third item; do not average mechanics
            # and art to disguise a visual regression.
            pairs.append(current["human_scores"][2] - old["human_scores"][2])
    pairs.sort()
    median = (pairs[(len(pairs) - 1) // 2] + pairs[len(pairs) // 2]) / 2 if pairs else None
    old_cost = by_variant["legacy"]["mean_accepted_cost_usd"]
    new_cost = by_variant["adaptive"]["mean_accepted_cost_usd"]
    cost_ratio = new_cost / old_cost if new_cost is not None and old_cost else None
    # An unfinished/failed run stays in the denominator. No cherry-picked success
    # subset, no substitute model-generated "human" rating, no default rollout.
    finished = all(r["outcome"] not in ("running", "not_started") for r in runs)
    gates = {
        "all_runs_finished": finished,
        "eight_of_ten_new_games": by_variant["adaptive"]["new_games_accepted"] >= 8,
        "five_revisions_without_required_regression": by_variant["adaptive"]["revisions_accepted"]
        == 5,
        "mechanics_success_not_decreased": by_variant["adaptive"]["new_games_accepted"]
        >= by_variant["legacy"]["new_games_accepted"]
        and by_variant["adaptive"]["revisions_accepted"]
        >= by_variant["legacy"]["revisions_accepted"],
        "accepted_mean_cost_increase_at_most_50_percent": cost_ratio is not None
        and cost_ratio <= 1.5,
        "complete_paired_human_review": len(pairs) == 15,
        "median_art_improvement_at_least_one_point": median is not None and median >= 1,
    }
    return {
        "schema_version": 1,
        "manifest_sha256": hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
        "comparison": manifest["version"],
        "model": manifest["model"],
        "budget_usd": manifest["budget_usd"],
        "spent_upper_usd": sum(r.get("upper_nano", 0) for r in ledger.values()) / 1e9,
        "reserved_usd": sum(r.get("reserved_nano", 0) for r in ledger.values()) / 1e9,
        "unscored_setup_spend_upper_usd": sum(r.get("upper_nano", 0) for r in ledger.values()) / 1e9
        - sum(r["cost_upper_usd"] for r in runs),
        "variants": by_variant,
        "accepted_cost_ratio": cost_ratio,
        "paired_human_art_median_improvement": median,
        "gates": gates,
        "default_rollout_eligible": all(gates.values()),
        "actual_webview": "host_unknown_not_tested",
        "runs": runs,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--ratings", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.root, load(args.ratings) if args.ratings else None)
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(content)
    else:
        print(content, end="")
