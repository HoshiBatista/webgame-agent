"""The same bounded, declarative contract drives providers and browser checks."""

from jsonschema import Draft202012Validator

from .errors import ContractError


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def string(**kwargs):
    return {"type": "string", **kwargs}


def array(items, **kwargs):
    return {"type": "array", "items": items, **kwargs}


POINT = obj(
    {
        "action": {"enum": ["click", "tap"]},
        "selector": {
            "type": ["string", "null"],
            "description": "Target element. With x=y=null, click its center.",
        },
        "x": {
            "type": ["number", "null"],
            "description": "Horizontal CSS pixels from the displayed element's top-left, or viewport if selector=null. Never normalized 0..1; null centers the element.",
        },
        "y": {
            "type": ["number", "null"],
            "description": "Vertical CSS pixels from the displayed element's top-left, or viewport if selector=null. Never normalized 0..1; null centers the element.",
        },
    }
)
FRACTION_POINT = obj(
    {
        "action": {"enum": ["click_fraction", "tap_fraction"]},
        "selector": string(minLength=1, maxLength=200),
        "x": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Fraction of the displayed element width, from its left edge.",
        },
        "y": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Fraction of the displayed element height, from its top edge.",
        },
    }
)
KEY = obj({"action": {"enum": ["press", "key_down", "key_up"]}, "key": string(minLength=1, maxLength=40)})
WAIT = obj({"action": {"enum": ["wait"]}, "ms": {"type": "integer", "minimum": 0, "maximum": 10000}})
BLUR = obj({"action": {"enum": ["blur"]}})
OBSERVATION = {
    "anyOf": [
        obj({"source": {"enum": ["text"]}, "selector": string(minLength=1, maxLength=200)}),
        obj(
            {
                "source": {"enum": ["attribute"]},
                "selector": string(minLength=1, maxLength=200),
                "attribute": string(minLength=1, maxLength=80),
            }
        ),
        obj(
            {
                "source": {"enum": ["state"]},
                "path": string(
                    pattern=r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\.\d+)*$",
                    maxLength=200,
                    description="Read-only path from window through own data properties only. No getters, inherited properties, functions, or self-reported test results. Optional alternative to DOM text/attributes; no prescribed state names.",
                ),
            }
        ),
    ]
}
CHECK_SCHEMA = obj(
    {
        "id": string(pattern=r"^[a-zA-Z0-9_-]+$", minLength=1, maxLength=80),
        "category": {"enum": ["start", "control", "outcome", "regression"]},
        "requirement": string(minLength=8, maxLength=500),
        "viewport": {"enum": ["mobile", "desktop"]},
        "steps": array({"anyOf": [POINT, FRACTION_POINT, KEY, WAIT, BLUR]}, maxItems=30),
        "observation": OBSERVATION,
        "expect": obj(
            {
                "operator": {
                    "enum": ["eq", "not_eq", "contains", "changed", "increased", "decreased", "visible"]
                },
                "value": {"type": ["string", "number", "boolean", "null"]},
            }
        ),
    }
)
DESIGN = obj(
    {
        "summary": string(maxLength=1000),
        "visual": string(
            maxLength=1200,
            description="Concrete spatial plan before code: rule-imposed vs flexible geometry; usable CSS width/height after controls on phone and desktop; actual interactive/drawn field dimensions and object/cell size (approximate values or formulas); shared drawing/input/resize mapping. Canvas element size or a claim of filling it is not evidence of useful play space. Preserve geometry required by the rules.",
        ),
        "controls": array(string(maxLength=200), maxItems=12),
        "outcome": string(maxLength=500),
    }
)
RESPONSE_SCHEMA = obj(
    {
        "status": {"enum": ["ok", "scope_refusal", "unchanged"]},
        "operation": {"enum": ["create", "edit", "repair"]},
        "title": string(maxLength=120),
        "message": string(maxLength=2000),
        "design": DESIGN,
        "base_revision": {"type": ["string", "null"]},
        "files": array(
            obj({"path": string(maxLength=120), "content": string(maxLength=300000)}), maxItems=20
        ),
        "patches": array(
            obj(
                {
                    "path": string(maxLength=120),
                    "file_hash": {"type": ["string", "null"]},
                    "old_text": string(maxLength=100000),
                    "new_text": string(maxLength=100000),
                }
            ),
            maxItems=80,
        ),
        "checks": array(CHECK_SCHEMA, maxItems=12),
    }
)


def validate_response(response, *, operation=None):
    errors = sorted(
        Draft202012Validator(RESPONSE_SCHEMA).iter_errors(response), key=lambda e: str(list(e.path))
    )
    if errors:
        error = errors[0]
        raise ContractError(
            "invalid_schema",
            f"Ответ не соответствует формату в {'.'.join(map(str, error.path))}: {error.message[:500]}",
        )
    if operation is not None and response["operation"] != operation:
        raise ContractError(
            "operation_mismatch",
            "Ответ изменил вид операции. Используйте operation из текущего запроса приложения.",
        )
    if response["status"] == "scope_refusal":
        if not response["message"].strip() or response["files"] or response["patches"]:
            raise ContractError("invalid_refusal", "Отказ должен объяснять ограничение и не изменять игру.")
        return
    if response["status"] == "unchanged":
        if (
            response["operation"] not in {"edit", "repair"}
            or not response["base_revision"]
            or not response["message"].strip()
            or any(response[name] for name in ("files", "patches", "checks"))
        ):
            raise ContractError(
                "invalid_unchanged",
                "Ответ «без изменений» требует существующей базовой версии, объяснения и пустых files/patches/checks.",
            )
        return
    partial = response["operation"] in {"edit", "repair"} and response["base_revision"] is not None
    validate_checks(response["checks"], require_complete=not partial)
    if not response["title"].strip():
        raise ContractError("missing_title", "Модель не предложила название игры.")


def validate_checks(checks, *, require_complete=True):
    if len(checks) > 12:
        raise ContractError(
            "too_many_checks", "Итоговый набор мини-игры должен содержать не более 12 проверок."
        )
    ids = set()
    categories = set()
    for check in checks:
        error = next(Draft202012Validator(CHECK_SCHEMA).iter_errors(check), None)
        if error:
            raise ContractError("invalid_check", f"Неверная проверка: {error.message[:300]}")
        if check["id"] in ids:
            raise ContractError("duplicate_check", "Идентификаторы проверок должны быть уникальны.")
        ids.add(check["id"])
        categories.add(check["category"])
        if sum(step.get("ms", 0) for step in check["steps"]) > 10000:
            raise ContractError(
                "long_check",
                "Один smoke-сценарий может ожидать не более 10 секунд; долгий исход проверьте вручную.",
            )
        if check["category"] in {"control", "outcome"} and not any(
            s["action"] in {"click", "tap", "click_fraction", "tap_fraction", "press", "key_down"}
            for s in check["steps"]
        ):
            raise ContractError(
                "no_real_input", "Проверка управления/исхода должна использовать реальный ввод."
            )
        observation = check["observation"]
        if observation["source"] == "state":
            parts = observation["path"].lower().split(".")
            if any(
                p in {"__proto__", "constructor", "prototype", "passed", "testpassed", "test_passed"}
                for p in parts
            ):
                raise ContractError(
                    "self_report_check", "Проверяйте игровой эффект, а не игровой самоотчёт passed."
                )
        for step in check["steps"]:
            if step["action"] in {"click", "tap"}:
                if (step["x"] is None) != (step["y"] is None) or (not step["selector"] and step["x"] is None):
                    raise ContractError("invalid_pointer", "Укажите selector или обе координаты действия.")
    if require_complete and not {"start", "control", "outcome"}.issubset(categories):
        raise ContractError(
            "missing_effects", "Нужны проверки начала, управления и победы либо поражения конкретной игры."
        )
