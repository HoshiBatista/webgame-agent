"""Run a bounded GPT-6 Luna golden evaluation and emit a secret-free JSON report."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prompt2play.adapters.openai_gateway import OpenAIModelGateway
from prompt2play.config import Settings
from prompt2play.evaluation import load_golden_cases, score_candidate
from prompt2play.validation.browser import validate_in_browser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("golden/evals/cases.json"))
    parser.add_argument("--output", type=Path, default=Path("eval-results/live-eval.json"))
    parser.add_argument("--limit", type=int, default=7)
    parser.add_argument("--minimum-pass-rate", type=float, default=0.8)
    parser.add_argument("--browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings()
    gateway = OpenAIModelGateway(settings)
    cases = load_golden_cases(args.dataset)[: max(1, args.limit)]
    results: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for case in cases:
        try:
            specification = gateway.specify(case.prompt, "Live CI eval: no product analytics")
            candidate = gateway.generate(case.prompt, specification.value)
            score = score_candidate(case, specification.value, candidate.value.html)
            total_input_tokens += specification.input_tokens + candidate.input_tokens
            total_output_tokens += specification.output_tokens + candidate.output_tokens
            browser_passed: bool | None = None
            browser_findings: list[str] = []
            if args.browser:
                with tempfile.TemporaryDirectory(prefix="prompt2play-eval-") as directory:
                    entrypoint = Path(directory) / "index.html"
                    entrypoint.write_text(candidate.value.html, encoding="utf-8")
                    browser_passed, findings, _ = validate_in_browser(entrypoint, 15_000)
                    browser_findings = [finding.code for finding in findings]
            passed = score.passed and (browser_passed is True if args.browser else True)
            results.append(
                {
                    "case_id": case.id,
                    "passed": passed,
                    "score": score.score,
                    "criteria": score.criteria,
                    "finding_codes": score.finding_codes,
                    "browser_passed": browser_passed,
                    "browser_finding_codes": browser_findings,
                    "input_tokens": specification.input_tokens + candidate.input_tokens,
                    "output_tokens": specification.output_tokens + candidate.output_tokens,
                    "latency_ms": specification.latency_ms + candidate.latency_ms,
                }
            )
        except Exception as exc:  # A failed provider case is an eval failure, not a crashed suite.
            results.append(
                {
                    "case_id": case.id,
                    "passed": False,
                    "error_type": type(exc).__name__,
                }
            )

    passed_count = sum(bool(result["passed"]) for result in results)
    pass_rate = passed_count / len(results)
    report = {
        "schema_version": "1",
        "created_at": datetime.now(UTC).isoformat(),
        "model": gateway.model_name,
        "dataset": str(args.dataset),
        "case_count": len(results),
        "passed_count": passed_count,
        "pass_rate": pass_rate,
        "minimum_pass_rate": args.minimum_pass_rate,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key != "results"}, indent=2))
    return 0 if pass_rate >= args.minimum_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
