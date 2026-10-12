"""Application repair selection is independent of provider orchestration."""

from prompt2play.application.policy import decide, repair_route


def test_local_and_dependency_repair_scope() -> None:
    report: dict[str, object] = {
        "checks": [
            {
                "status": "failed",
                "name": "syntax",
                "affected_files": ["game.js"],
                "message": "unexpected token",
            }
        ]
    }
    route = repair_route(report, ["game.js", "style.css"])
    assert route.strategy == "local" and route.files == ("game.js",)
    report["checks"] = [{"status": "failed", "scope": "integration", "affected_files": ["game.js"]}]
    assert repair_route(report, ["game.js", "style.css"]).strategy == "structural"


def test_contract_replan_and_repeated_failure_regeneration() -> None:
    report: dict[str, object] = {
        "review": {
            "issues": [
                {
                    "scope": "contract",
                    "contract_ids": ["input"],
                    "affected_files": ["game.js"],
                    "file": "game.js",
                }
            ]
        }
    }
    route = repair_route(report, ["game.js", "style.css"])
    assert route.strategy == "replan"
    repeated = repair_route(report, ["game.js", "style.css"], route.fingerprint)
    assert repeated.strategy == "regenerate"
    assert repeated.files == ("game.js", "style.css")


def test_unclassified_defect_repairs_available_files_and_ignores_unknown_paths() -> None:
    report: dict[str, object] = {
        "checks": [{"status": "failed", "affected_files": ["../../private"]}]
    }
    route = repair_route(report, ["game.js", "style.css"])
    assert route.strategy == "structural"
    assert route.files == ("game.js", "style.css")
    assert repair_route({"checks": "malformed", "review": []}, ["game.js"]).strategy == "local"


def test_failure_attempt_budget_and_unverified_stops() -> None:
    report: dict[str, object] = {"status": "failed", "errors": ["fixture"]}
    assert decide(report, 1, 2).action == "repair"
    assert decide(report, 3, 2).action == "stop"
    skipped: dict[str, object] = {"status": "unverified", "checks": [{"status": "skipped"}]}
    assert decide(skipped, 1, 2).outcome == "unverified"
    assert decide(skipped, 1, 2).action == "stop"
    assert (
        decide({"status": "passed", "checks": [{"status": "passed"}]}, 1, 2).outcome == "unverified"
    )


def test_optional_completion_never_relaxes_other_required_checks() -> None:
    from typing import Any

    from prompt2play.validation import REQUIRED_CHECKS

    report: dict[str, Any] = {
        "status": "passed",
        "completion_required": False,
        "checks": [
            {"name": name, "status": "skipped" if name.startswith("completion:") else "passed"}
            for name in REQUIRED_CHECKS
        ],
        "scope": {"isolated": True, "real_input": True},
        "suite_sha256": "x",
        "validator_image_sha256": "y",
    }
    assert decide(report, 1, 2).action == "promote"
    report["completion_required"] = True
    assert decide(report, 1, 2).outcome == "unverified"
    report["completion_required"] = False
    next(c for c in report["checks"] if c["name"] == "input:1280")["status"] = "skipped"
    assert decide(report, 1, 2).outcome == "unverified"
