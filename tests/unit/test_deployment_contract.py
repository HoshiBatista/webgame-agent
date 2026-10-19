"""Deployment boundaries that protect credentials and generated code."""

from pathlib import Path
from shlex import shlex
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("service_name", "expected_command"),
    [("postgres", "pg_isready -U prompt2play"), ("redis", "redis-cli ping")],
)
def test_ci_healthcheck_is_one_runner_argument(service_name: str, expected_command: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    service = workflow["jobs"]["integration"]["services"][service_name]
    # Actions passes options to a process, not a shell: single quotes do not
    # group arguments. Model double-quote grouping rather than POSIX shlex.split.
    lexer = shlex(service["options"], posix=True)
    lexer.quotes = '"'
    lexer.whitespace_split = True
    lexer.commenters = ""
    arguments = list(lexer)
    assert f"--health-cmd={expected_command}" in arguments
    assert "-U" not in arguments


def load_compose() -> dict[str, Any]:
    """Load Compose after YAML anchors have been resolved."""

    return cast(dict[str, Any], yaml.safe_load((ROOT / "compose.yaml").read_text()))


def test_only_model_worker_receives_model_credentials_and_egress() -> None:
    services = cast(dict[str, dict[str, Any]], load_compose()["services"])
    for secret_name in ("OPENAI_API_KEY", "P2P_VLLM_API_KEY"):
        secret_holders = {
            name
            for name, service in services.items()
            if secret_name in cast(dict[str, object], service.get("environment", {}))
        }
        assert secret_holders == {"worker-models"}
    assert services["worker-models"]["networks"] == ["backend", "model-egress"]
    assert services["worker-validation"]["networks"] == ["backend"]
    assert services["api"]["networks"] == ["backend"]


def test_runtime_roles_use_separate_targets_and_least_privilege_mounts() -> None:
    services = cast(dict[str, dict[str, Any]], load_compose()["services"])
    expected_targets = {
        "api": "api",
        "migrate": "migration",
        "worker-models": "model-worker",
        "worker-workflow": "workflow-worker",
        "worker-validation": "validation-worker",
        "beat": "beat",
    }
    for service_name, target in expected_targets.items():
        service = services[service_name]
        assert service["build"]["target"] == target
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]

    assert services["api"]["volumes"] == ["artifacts:/data/artifacts:ro"]
    assert services["worker-validation"]["volumes"] == [
        "artifacts:/data/artifacts:ro",
        "validation-evidence:/data/validation",
    ]
    assert services["worker-models"]["volumes"] == ["artifacts:/data/artifacts"]


def test_only_nginx_publishes_a_host_port() -> None:
    services = cast(dict[str, dict[str, Any]], load_compose()["services"])
    published = {name for name, service in services.items() if "ports" in service}
    assert published == {"web"}
    assert services["api"]["expose"] == ["8000"]
    assert services["web"]["networks"] == ["edge", "backend"]


def test_browser_dependencies_exist_only_in_validation_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    common, validation = dockerfile.split("FROM python-runtime AS validation-worker", maxsplit=1)
    assert "playwright install" not in common
    assert "playwright install --with-deps chromium" in validation
    for target in (
        "api",
        "migration",
        "model-worker",
        "workflow-worker",
        "beat",
        "validation-worker",
    ):
        assert f" AS {target}" in dockerfile


def test_nginx_is_same_origin_gateway_with_streaming_and_rate_limits() -> None:
    config = (ROOT / "web/nginx.conf").read_text(encoding="utf-8")
    assert "server api:8000" in config
    assert "location /v1/" in config
    assert "location /play/" in config
    assert "proxy_buffering off" in config
    assert "proxy_read_timeout 1h" in config
    assert "limit_req zone=generation" in config
    assert "Content-Security-Policy" in config
