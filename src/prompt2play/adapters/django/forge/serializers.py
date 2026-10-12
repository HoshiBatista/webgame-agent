import json
import math
from decimal import Decimal

from rest_framework import serializers

from .artifacts import require_report_binding

MIB = 1024 * 1024
MODULE_NAMES = frozenset({"engine.js", "renderer.js", "audio.js", "ui.js", "tests.js"})
REQUIRED_MODULES = MODULE_NAMES - {"tests.js"}


def bounded_object(value, max_bytes, label="object"):
    if not isinstance(value, dict):
        raise serializers.ValidationError(f"{label}: ожидается JSON-объект.")
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise serializers.ValidationError(f"{label}: некорректный JSON.") from exc
    if len(raw) > max_bytes:
        raise serializers.ValidationError(f"{label}: превышен допустимый размер.")
    return value


def validate_files(value, required=True):
    bounded_object(value, 8 * MIB, "files")
    if not set(value).issubset(MODULE_NAMES):
        raise serializers.ValidationError(
            "Разрешены только engine.js, renderer.js, audio.js, ui.js и tests.js."
        )
    if required and not REQUIRED_MODULES.issubset(value):
        raise serializers.ValidationError(
            "Нужны четыре модуля: engine.js, renderer.js, audio.js, ui.js."
        )
    for name, content in value.items():
        if not isinstance(content, str) or len(content.encode("utf-8")) > 2 * MIB:
            raise serializers.ValidationError(f"{name}: ожидается строка не более 2 MiB.")
        if required and name in REQUIRED_MODULES and not content.strip():
            raise serializers.ValidationError(f"{name}: модуль не должен быть пустым.")
    return value


class UsageSerializer(serializers.Serializer):
    input_tokens = serializers.IntegerField(min_value=0, max_value=10**12, default=0)
    cached_input_tokens = serializers.IntegerField(min_value=0, max_value=10**12, default=0)
    output_tokens = serializers.IntegerField(min_value=0, max_value=10**12, default=0)
    total_tokens = serializers.IntegerField(min_value=0, max_value=10**12, default=0)
    calls = serializers.IntegerField(min_value=0, max_value=100000, default=0)

    def validate(self, attrs):
        if attrs["cached_input_tokens"] > attrs["input_tokens"]:
            raise serializers.ValidationError(
                "Кешированные входные токены не могут превышать все входные токены."
            )
        if attrs["total_tokens"] != attrs["input_tokens"] + attrs["output_tokens"]:
            raise serializers.ValidationError(
                "total_tokens должен равняться input_tokens + output_tokens."
            )
        return attrs


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=1024, trim_whitespace=False)


class ProjectCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    prompt = serializers.CharField(max_length=12000)


class ProjectUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)


class JobCreateSerializer(serializers.Serializer):
    creation_mode = serializers.ChoiceField(choices=["lite", "pro"], default="lite")
    kind = serializers.ChoiceField(choices=["generate", "revise"])
    prompt = serializers.CharField(max_length=12000)
    provider = serializers.ChoiceField(choices=["codex", "openai"])
    model = serializers.CharField(max_length=120, allow_blank=True, default="")
    base_version_id = serializers.UUIDField(allow_null=True, required=False)
    max_repairs = serializers.IntegerField(min_value=0, max_value=2, default=2)
    playthrough_mode = serializers.ChoiceField(choices=["manual", "auto"], default="manual")
    budget_tokens = serializers.IntegerField(min_value=1000, max_value=2000000, default=400000)
    budget_usd = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("1000.00"),
        required=False,
    )
    budget_seconds = serializers.IntegerField(
        min_value=1, max_value=3600, default=None, allow_null=True
    )

    def validate(self, attrs):
        if "budget_usd" in self.initial_data and "budget_tokens" in self.initial_data:
            raise serializers.ValidationError(
                "Укажите один вид бюджета: доллары или устаревший лимит токенов."
            )
        return attrs


class RunnerCreateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["generator", "validator"], default="generator")
    name = serializers.CharField(max_length=120)


class BudgetExtensionSerializer(serializers.Serializer):
    stage_fence = serializers.IntegerField(min_value=0)
    playthrough_mode = serializers.ChoiceField(choices=["manual", "auto"], required=False)
    budget_usd = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("1000.00"),
        required=False,
    )
    budget_tokens = serializers.IntegerField(min_value=1000, max_value=1000000000, required=False)

    def validate(self, attrs):
        if ("budget_usd" in attrs) == ("budget_tokens" in attrs):
            raise serializers.ValidationError("Укажите один новый общий лимит.")
        return attrs


class ClaimSerializer(serializers.Serializer):
    capabilities = serializers.JSONField()
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate_capabilities(self, value):
        bounded_object(value, 32768, "capabilities")
        providers = value.get("providers")
        if (
            not isinstance(providers, list)
            or not 1 <= len(providers) <= 2
            or any(p not in ["codex", "openai"] for p in providers)
        ):
            raise serializers.ValidationError("providers должен содержать codex и/или openai.")
        if not isinstance(value.get("model", ""), str) or len(value.get("model", "")) > 120:
            raise serializers.ValidationError("Некорректная модель исполнителя.")
        if "codex_models" in value:
            models = value["codex_models"]
            if (
                "codex" not in providers
                or not isinstance(models, list)
                or len(models) > 64
                or value.get("model_catalog_status") not in ["ready", "unavailable"]
                or not isinstance(value.get("model_catalog_checked_at"), str)
                or len(value["model_catalog_checked_at"]) > 40
            ):
                raise serializers.ValidationError("Некорректный каталог моделей Codex.")
            seen = set()
            for model in models:
                if (
                    not isinstance(model, dict)
                    or set(model) != {"id", "label", "is_default"}
                    or not isinstance(model["is_default"], bool)
                    or any(
                        not isinstance(model[key], str)
                        or not 1 <= len(model[key]) <= 120
                        or any(ord(char) < 32 for char in model[key])
                        for key in ["id", "label"]
                    )
                    or model["id"] in seen
                ):
                    raise serializers.ValidationError("Некорректная запись каталога моделей.")
                seen.add(model["id"])
            if value["model_catalog_status"] == "unavailable" and models:
                raise serializers.ValidationError("Недоступный каталог должен быть пустым.")
        if value.get("validator", "static") not in ["static", "docker"]:
            raise serializers.ValidationError("validator: static или docker.")
        if (
            "continuable_authoring_v1" in value
            and type(value["continuable_authoring_v1"]) is not bool
        ):
            raise serializers.ValidationError("continuable_authoring_v1 must be boolean.")
        if "interactive_plan_v1" in value and type(value["interactive_plan_v1"]) is not bool:
            raise serializers.ValidationError("interactive_plan_v1 must be boolean.")
        requires = value.get("requires_job_model", [])
        if (
            not isinstance(requires, list)
            or len(requires) > 2
            or any(not isinstance(p, str) or p not in providers for p in requires)
            or len(set(requires)) != len(requires)
        ):
            raise serializers.ValidationError("requires_job_model: уникальный список из providers.")
        return value


class LeaseSerializer(serializers.Serializer):
    lease_token = serializers.CharField(min_length=20, max_length=256, trim_whitespace=False)


class EventCreateSerializer(LeaseSerializer):
    stage = serializers.RegexField(r"^[a-z][a-z0-9_-]*$", max_length=32)
    progress = serializers.FloatField(min_value=0, max_value=100)
    level = serializers.ChoiceField(choices=["info", "warning", "error"])
    message = serializers.CharField(max_length=2000)
    data = serializers.JSONField(default=dict)

    def validate_progress(self, value):
        if not math.isfinite(value):
            raise serializers.ValidationError("progress должен быть конечным числом от 0 до 100.")
        return value

    def validate_data(self, value):
        return bounded_object(value, 64 * 1024, "data")


class CheckpointSerializer(LeaseSerializer):
    checkpoint = serializers.JSONField()
    usage = UsageSerializer(required=False)

    def validate_checkpoint(self, value):
        return bounded_object(value, 12 * MIB, "checkpoint")


class ValidationCheckSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    status = serializers.ChoiceField(choices=["passed", "failed", "skipped"])
    message = serializers.CharField(max_length=2000, allow_blank=True, default="")
    check_kind = serializers.RegexField(r"^[a-z][a-z0-9_-]*$", max_length=64)
    artifact_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    scenario_id = serializers.CharField(max_length=160, required=False, allow_blank=True)
    affected_files = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(REQUIRED_MODULES)),
        max_length=4,
        required=False,
    )
    command = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    limitations = serializers.ListField(
        child=serializers.CharField(max_length=2000), max_length=30, default=list
    )
    evidence = serializers.JSONField(default=dict)

    def validate_evidence(self, value):
        return bounded_object(value, 32 * 1024, "evidence")


class ArtifactSerializer(serializers.Serializer):
    html_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    html_bytes = serializers.IntegerField(min_value=1, max_value=8 * MIB)
    files_sha256 = serializers.DictField(child=serializers.RegexField(r"^[a-f0-9]{64}$"))
    spec_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")

    def validate_files_sha256(self, value):
        if not REQUIRED_MODULES.issubset(value) or not set(value).issubset(MODULE_NAMES):
            raise serializers.ValidationError(
                "Хеши должны покрывать все переданные игровые модули."
            )
        return value


class ReviewIssueSerializer(serializers.Serializer):
    file = serializers.ChoiceField(choices=sorted(REQUIRED_MODULES))
    severity = serializers.ChoiceField(choices=["error", "warning"])
    message = serializers.CharField(max_length=4000)
    scope = serializers.ChoiceField(choices=["local", "integration", "contract"])
    affected_files = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(REQUIRED_MODULES)), min_length=1, max_length=4
    )
    contract_ids = serializers.ListField(child=serializers.CharField(max_length=160), max_length=50)
    reproduction = serializers.CharField(max_length=4000, allow_blank=True)
    expected = serializers.CharField(max_length=4000, allow_blank=True)
    observed = serializers.CharField(max_length=4000, allow_blank=True)
    regression_scenario_id = serializers.CharField(max_length=160, allow_blank=True)


class ModelReviewSerializer(serializers.Serializer):
    approved = serializers.BooleanField()
    summary = serializers.CharField(max_length=6000, allow_blank=True)
    issues = ReviewIssueSerializer(many=True, max_length=50)
    provider = serializers.CharField(max_length=120)
    model = serializers.CharField(max_length=120, allow_blank=True)
    contract_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    prompt_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    artifact_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")

    def validate(self, value):
        if not value["approved"] or any(issue["severity"] == "error" for issue in value["issues"]):
            raise serializers.ValidationError(
                "Нельзя сохранить версию с блокирующими замечаниями ревью."
            )
        return value


class ValidationSerializer(serializers.Serializer):
    schema_version = serializers.ChoiceField(choices=[2])
    artifact = ArtifactSerializer()
    status = serializers.ChoiceField(choices=["passed", "partial", "failed"])
    checks = ValidationCheckSerializer(many=True, max_length=100)
    errors = serializers.ListField(child=serializers.CharField(max_length=4000), max_length=100)
    warnings = serializers.ListField(child=serializers.CharField(max_length=4000), max_length=100)
    review = ModelReviewSerializer()
    provenance = serializers.JSONField(default=dict)

    def validate_provenance(self, value):
        bounded_object(value, 256 * 1024, "provenance")
        if set(value) - {"calls", "iterations", "module_summaries"}:
            raise serializers.ValidationError(
                "provenance содержит только calls, iterations и module_summaries."
            )
        if any(
            not isinstance(value.get(name, []), list) or len(value.get(name, [])) > 200
            for name in ("calls", "iterations")
        ):
            raise serializers.ValidationError(
                "calls и iterations должны быть ограниченными списками."
            )
        summaries = value.get("module_summaries", {})
        if (
            not isinstance(summaries, dict)
            or set(summaries) - {"engine", "renderer", "audio", "ui"}
            or any(not isinstance(text, str) or len(text) > 2000 for text in summaries.values())
        ):
            raise serializers.ValidationError(
                "module_summaries: до четырёх описаний модулей не более 2000 символов."
            )
        return value

    def validate(self, value):
        bounded_object(value, MIB, "validation")
        if (
            value["status"] == "failed"
            or value["errors"]
            or any(c["status"] == "failed" for c in value["checks"])
        ):
            raise serializers.ValidationError(
                "Нельзя опубликовать версию с известными ошибками проверки."
            )
        if value["status"] == "passed" and (
            not value["checks"] or any(c["status"] == "skipped" for c in value["checks"])
        ):
            raise serializers.ValidationError(
                "При отсутствующих или пропущенных проверках укажите status=partial."
            )
        if value["status"] == "passed" and not any(
            c["status"] == "passed"
            and c["check_kind"] in {"browser", "browser_runtime", "scenario"}
            for c in value["checks"]
        ):
            raise serializers.ValidationError(
                "Статика и ревью модели не подтверждают запуск игры. Укажите status=partial."
            )
        return value


class CompleteSerializer(LeaseSerializer):
    html = serializers.CharField(trim_whitespace=False, max_length=8 * MIB)
    files = serializers.JSONField()
    spec = serializers.JSONField()
    summary = serializers.CharField(max_length=3000, allow_blank=True, default="")
    validation = ValidationSerializer()
    usage = UsageSerializer(required=False)

    def validate_html(self, value):
        try:
            encoded = value.encode("utf-8")
        except UnicodeError as exc:
            raise serializers.ValidationError(
                "HTML содержит некорректную последовательность Unicode."
            ) from exc
        if not value.strip() or len(encoded) > 8 * MIB or "\x00" in value:
            raise serializers.ValidationError("HTML пуст, содержит NUL или превышает 8 MiB.")
        return value

    def validate_files(self, value):
        return validate_files(value)

    def validate_spec(self, value):
        return bounded_object(value, 512 * 1024, "spec")

    def validate(self, value):
        try:
            require_report_binding(
                value["files"], value["html"], value["spec"], value["validation"]
            )
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise serializers.ValidationError(str(exc)) from exc
        if value["validation"]["status"] == "passed":
            planned = value["spec"].get("qa_scenarios", [])
            if isinstance(planned, list):
                expected = {
                    scenario.get("id")
                    for scenario in planned
                    if isinstance(scenario, dict) and isinstance(scenario.get("id"), str)
                }
                observed = {
                    check.get("scenario_id")
                    for check in value["validation"]["checks"]
                    if check["check_kind"] == "scenario"
                }
                if expected - observed:
                    raise serializers.ValidationError(
                        "Не все сценарии из плана выполнялись; укажите status=partial."
                    )
        return value


class FailSerializer(LeaseSerializer):
    error = serializers.CharField(max_length=4000)
    usage = UsageSerializer(required=False)


class FencedSerializer(LeaseSerializer):
    stage_fence = serializers.IntegerField(min_value=1)


class CandidateSerializer(FencedSerializer):
    idempotency_key = serializers.CharField(max_length=160)
    html = serializers.CharField(trim_whitespace=False, max_length=8 * MIB)
    files = serializers.JSONField()
    spec = serializers.JSONField()
    plan = serializers.JSONField(default=dict)
    provenance = serializers.JSONField(default=dict)
    format = serializers.ChoiceField(
        choices=["legacy-four-module-v1", "runtime-v1"], default="legacy-four-module-v1"
    )
    summary = serializers.CharField(max_length=3000, allow_blank=True, default="")
    usage = UsageSerializer(required=False)
    invocation_id = serializers.UUIDField(required=False)

    validate_html = CompleteSerializer.validate_html

    def validate_files(self, value):
        from pathlib import PurePosixPath

        bounded_object(value, 8 * MIB, "files")
        if len(value) > 100:
            raise serializers.ValidationError("Too many source files.")
        for name, source in value.items():
            path = PurePosixPath(name)
            try:
                source_bytes = source.encode("utf-8") if isinstance(source, str) else None
            except UnicodeError as exc:
                raise serializers.ValidationError("Source contains invalid Unicode.") from exc
            if (
                not name
                or path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != name
                or "\\" in name
                or "\x00" in name
                or source_bytes is None
                or len(source_bytes) > 2 * MIB
            ):
                raise serializers.ValidationError("Invalid source path or content.")
        return value

    def validate_spec(self, value):
        return bounded_object(value, 512 * 1024, "spec")

    def validate_plan(self, value):
        return bounded_object(value, 512 * 1024, "plan")

    def validate_provenance(self, value):
        return bounded_object(value, 512 * 1024, "provenance")


class ReserveSerializer(FencedSerializer):
    invocation_key = serializers.CharField(max_length=160)
    operation = serializers.CharField(max_length=64)
    prompt_sha256 = serializers.RegexField(r"^[a-f0-9]{64}$")
    reserved_tokens = serializers.IntegerField(min_value=1, max_value=10**8)
    reservation_input_tokens = serializers.IntegerField(
        min_value=1, max_value=10**8, required=False
    )
    reservation_output_tokens = serializers.IntegerField(
        min_value=1, max_value=10**8, required=False
    )


class SettleSerializer(FencedSerializer):
    invocation_id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=["completed", "ambiguous"])
    response = serializers.JSONField(default=dict)
    usage = UsageSerializer(required=False)
    invocation_usage = UsageSerializer(required=False)

    def validate_response(self, value):
        return bounded_object(value, 12 * MIB, "response")


class InvocationAccountSerializer(serializers.Serializer):
    invocation_id = serializers.UUIDField()
    invocation_usage = UsageSerializer()


class CandidateValidationSerializer(FencedSerializer):
    candidate_id = serializers.UUIDField()
    report = serializers.JSONField()
    evidence_files = serializers.JSONField(default=dict)

    def validate_report(self, value):
        return bounded_object(value, 2 * MIB, "report")

    def validate_evidence_files(self, value):
        return bounded_object(value, 48 * MIB, "evidence_files")


class PlanProposalSerializer(FencedSerializer):
    spec = serializers.JSONField()
    plan = serializers.JSONField()

    def validate_spec(self, value):
        return bounded_object(value, 512 * 1024, "spec")

    def validate_plan(self, value):
        return bounded_object(value, 512 * 1024, "plan")


class ReviewDecisionSerializer(serializers.Serializer):
    stage_fence = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=["approve", "revise"])
    feedback = serializers.CharField(max_length=12000, default="", allow_blank=True)


class DraftSerializer(FencedSerializer):
    draft = serializers.JSONField()

    def validate_draft(self, value):
        return bounded_object(value, 12 * MIB, "draft")


class DiagnosticSerializer(FencedSerializer):
    files = serializers.JSONField()
    html = serializers.CharField(trim_whitespace=False, max_length=8 * MIB)
    spec = serializers.JSONField()
    report = serializers.JSONField()
    evidence_files = serializers.JSONField(default=dict)
    validate_files = CandidateSerializer.validate_files
    validate_html = CompleteSerializer.validate_html
    validate_spec = CandidateSerializer.validate_spec
    validate_report = CandidateValidationSerializer.validate_report
    validate_evidence_files = CandidateValidationSerializer.validate_evidence_files
