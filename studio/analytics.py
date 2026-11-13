"""Bounded demonstration data, descriptive comparisons and atomic Run snapshots."""

import json
import re
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime

from generation.analytics import LABEL, validate_snapshot
from generation.audiences import AUDIENCES
from generation.errors import ContractError
from generation.requirements import digest

from .models import AnalyticsDataset

KEY = "hackathon-demo"
POLICY_VERSION = 1
MECHANICS = {
    "collection": "Сбор предметов", "matching": "Сопоставление объектов",
    "logic": "Логические задачи", "reaction": "Реакция",
}
COUNT_FIELDS = ("started", "finished", "replayed", "duration_observed", "active_ms_sum")
ROW_FIELDS = {"case_id", "family_id", "audience", "mechanic", "device", "input", "round_style", *COUNT_FIELDS}
HASH = re.compile(r"^[a-f0-9]{64}$")
IDENT = re.compile(r"^[a-z0-9_-]{1,64}$")


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "key", "version", "schema_version", "source", "label", "provenance",
        "period_start", "period_end", "as_of", "rows",
    }:
        raise ValueError("Неверная структура набора аналитики.")
    if (payload["key"] != KEY or payload["source"] != "demo" or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1 or type(payload["version"]) is not int or payload["version"] < 1):
        raise ValueError("Поддерживается только версионный демонстрационный набор v1.")
    for field, limit in (("label", 120), ("provenance", 500)):
        if not isinstance(payload[field], str) or not 1 <= len(payload[field].strip()) <= limit:
            raise ValueError("Неверное описание набора.")
    dates = []
    for field in ("period_start", "period_end", "as_of"):
        value = payload[field]
        try:
            parsed = parse_datetime(value) if isinstance(value, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("Период должен содержать ISO-время в UTC.")
        dates.append(parsed)
    if not dates[0] < dates[1] <= dates[2]:
        raise ValueError("Неверные границы периода.")
    rows = payload["rows"]
    if not isinstance(rows, list) or len(rows) > 128:
        raise ValueError("Набор превышает 128 строк.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise ValueError("Неверная структура строки.")
        if any(not isinstance(row[k], str) or not IDENT.fullmatch(row[k]) for k in ("case_id", "family_id")):
            raise ValueError("Неверный идентификатор случая.")
        if row["case_id"] in seen:
            raise ValueError("Повторяющийся case_id.")
        seen.add(row["case_id"])
        if (not all(isinstance(row[k], str) for k in ("audience", "mechanic", "round_style", "device", "input"))
                or row["audience"] not in AUDIENCES or row["mechanic"] not in MECHANICS
                or row["round_style"] not in {"short", "standard"}
                or row["device"] != "mobile" or row["input"] != "touch"):
            raise ValueError("Несовместимая когорта.")
        if any(type(row[k]) is not int for k in COUNT_FIELDS):
            raise ValueError("Счётчики должны быть целыми числами, не bool.")
        if not (0 <= row["replayed"] <= row["finished"] <= row["started"] <= 1_000_000
                and 0 <= row["duration_observed"] <= row["started"]
                and 0 <= row["active_ms_sum"] <= row["duration_observed"] * 900_000):
            raise ValueError("Несогласованные счётчики.")
    try:
        size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("Некорректный JSON набора.") from exc
    if size > 128 * 1024:
        raise ValueError("Набор превышает 128 КиБ.")
    return payload


def checked(dataset):
    payload = validate_payload(dataset.payload)
    if (digest(payload) != dataset.payload_hash or dataset.key != payload["key"]
            or dataset.version != payload["version"] or dataset.source != payload["source"]
            or dataset.schema_version != payload["schema_version"]):
        raise ValueError("Не совпадает идентичность набора.")
    return payload


def aggregate(rows):
    totals = {key: sum(row[key] for row in rows) for key in COUNT_FIELDS}
    families = defaultdict(int)
    for row in rows:
        families[row["family_id"]] += row["started"]
    n = totals["started"]
    return {
        **totals, "families": len(families), "largest_family_started": max(families.values(), default=0),
        "smallest_family_started": min(families.values(), default=0),
        "cases_hash": digest(sorted(row["case_id"] for row in rows)),
        "finish_rate": round(100 * totals["finished"] / n, 1) if n else None,
        "replay_rate": round(100 * totals["replayed"] / n, 1) if n else None,
        "mean_active_seconds": round(totals["active_ms_sum"] / totals["duration_observed"] / 1000, 1)
        if totals["duration_observed"] else None,
    }


def supported(group):
    return (group["started"] >= 100 and group["families"] >= 3
            and group["smallest_family_started"] >= 30
            and 2 * group["largest_family_started"] <= group["started"])


def recommendations(payload, audience):
    rows = [r for r in payload["rows"] if r["audience"] == audience]
    candidates = []
    for mechanic in sorted(MECHANICS):
        for style in ("short", "standard"):
            selected = [r for r in rows if r["mechanic"] == mechanic and r["round_style"] == style]
            others = [r for r in rows if r["mechanic"] != mechanic and r["round_style"] == style]
            candidates.append(("mechanic", mechanic, style, selected, others,
                               {"round_style": style, "mechanic_not": mechanic}))
        selected = [r for r in rows if r["mechanic"] == mechanic and r["round_style"] == "short"]
        others = [r for r in rows if r["mechanic"] == mechanic and r["round_style"] == "standard"]
        candidates.append(("short_round", mechanic, "short", selected, others,
                           {"round_style": "standard", "mechanic": mechanic}))
    proposals = []
    for rule, mechanic, style, selected, others, baseline_filter in candidates:
        candidate, baseline = aggregate(selected), aggregate(others)
        if not supported(candidate) or not supported(baseline):
            continue
        finish_delta = (Fraction(candidate["finished"], candidate["started"])
                        - Fraction(baseline["finished"], baseline["started"]))
        replay_delta = (Fraction(candidate["replayed"], candidate["started"])
                        - Fraction(baseline["replayed"], baseline["started"]))
        if finish_delta < Fraction(1, 10) or replay_delta < (Fraction(1, 20) if rule == "mechanic" else 0):
            continue
        scope = {"mechanic": mechanic, "round_style": style}
        advice = (f"Если это подходит вашей задумке, рассмотрите механику «{MECHANICS[mechanic].lower()}»."
                  if rule == "mechanic" else
                  f"Для механики «{MECHANICS[mechanic].lower()}» можно попробовать короткую партию с одной ясной целью.")
        evidence = {"candidate": candidate, "baseline": baseline, "baseline_filter": baseline_filter,
                    "finish_delta_pp": float(round(100 * finish_delta, 1)),
                    "replay_delta_pp": float(round(100 * replay_delta, 1))}
        ident = digest([POLICY_VERSION, digest(payload), audience, rule, scope, baseline_filter, advice, evidence])
        proposals.append({
            "id": ident, "rule_id": rule, "scope": scope, "advice": advice,
            "evidence": evidence,
            "_rank": (-finish_delta, -replay_delta, -candidate["families"], ident),
        })
    result = []
    for proposal in sorted(proposals, key=lambda item: item["_rank"]):
        if any(p["rule_id"] == proposal["rule_id"] or p["scope"]["mechanic"] != proposal["scope"]["mechanic"]
               for p in result):
            continue
        result.append({k: v for k, v in proposal.items() if k != "_rank"})
        if len(result) == 2:
            break
    return result


def snapshot_for(dataset, audience, ideas):
    payload = dataset.payload
    context = (f"{LABEL}; это вымышленные наблюдения, не статистика клиентов. "
               f"Аудитория: {audience}. Период: {payload['period_start']} — {payload['period_end']}.\n")
    for idea in ideas:
        a, b = idea["evidence"]["candidate"], idea["evidence"]["baseline"]
        context += (f"{idea['advice']} В демоданных: завершения {a['finished']}/{a['started']} "
                    f"против {b['finished']}/{b['started']}; повторы {a['replayed']}/{a['started']} "
                    f"против {b['replayed']}/{b['started']}.\n")
    snapshot = {
        "version": 1, "source": "demo", "dataset_id": str(dataset.id), "dataset_hash": dataset.payload_hash,
        "dataset_version": dataset.version, "policy_version": POLICY_VERSION, "audience": audience,
        **{k: payload[k] for k in ("label", "period_start", "period_end", "as_of")},
        "recommendations": deepcopy(ideas), "model_context": context,
    }
    snapshot["snapshot_hash"] = digest(snapshot)
    return validate_snapshot(snapshot)


def summary(dataset, audience):
    payload = checked(dataset)
    rows = [r for r in payload["rows"] if r["audience"] == audience]
    groups = [
        {"mechanic": m, "label": MECHANICS[m], "round_style": style,
         **aggregate([r for r in rows if r["mechanic"] == m and r["round_style"] == style])}
        for m in sorted(MECHANICS) for style in ("short", "standard")
        if any(r["mechanic"] == m and r["round_style"] == style for r in rows)
    ]
    ideas = recommendations(payload, audience)
    if ideas:
        snapshot_for(dataset, audience, ideas)
    return {
        "dataset": {"id": str(dataset.id), "hash": dataset.payload_hash, "version": dataset.version,
                    **{k: payload[k] for k in ("source", "label", "period_start", "period_end", "as_of")}},
        "policy_version": POLICY_VERSION, "audience": audience, "groups": groups, "recommendations": ideas,
        "data_status": "empty" if not rows else "ready" if any(supported(g) for g in groups) else "insufficient_data",
    }


def normalize_selection(value):
    from .services import DomainError

    if value is None:
        return None
    valid = isinstance(value, dict) and set(value) == {
        "dataset_id", "dataset_hash", "policy_version", "recommendation_ids",
    }
    if valid:
        import uuid

        try:
            dataset_id = str(uuid.UUID(value["dataset_id"])) if isinstance(value["dataset_id"], str) else None
        except ValueError:
            dataset_id = None
        ids = value["recommendation_ids"]
        valid = (dataset_id and isinstance(value["dataset_hash"], str) and HASH.fullmatch(value["dataset_hash"])
                 and type(value["policy_version"]) is int and value["policy_version"] > 0
                 and isinstance(ids, list) and 1 <= len(ids) <= 2
                 and all(isinstance(i, str) and HASH.fullmatch(i) for i in ids) and len(set(ids)) == len(ids))
    if not valid:
        raise DomainError("invalid_analytics_selection", "Выберите идеи из доступной аналитики.")
    return {**value, "dataset_id": dataset_id, "recommendation_ids": sorted(ids)}


def resolve_snapshot(selection, audience):
    from .services import DomainError

    if not settings.GAMEFORGE_ANALYTICS_ENABLED:
        raise DomainError("analytics_disabled", "Аналитика отключена. Уберите выбранные идеи.", 409)
    dataset = AnalyticsDataset.objects.select_for_update().filter(
        pk=selection["dataset_id"], key=KEY, enabled=True,
    ).first()
    if (dataset is None or dataset.payload_hash != selection["dataset_hash"]
            or selection["policy_version"] != POLICY_VERSION):
        raise DomainError("analytics_selection_stale", "Данные изменились. Обновите или уберите выбранные идеи.", 409)
    try:
        current = summary(dataset, audience)
        ideas = [i for i in current["recommendations"] if i["id"] in selection["recommendation_ids"]]
        if len(ideas) != len(selection["recommendation_ids"]):
            raise DomainError("analytics_selection_stale", "Идеи больше не соответствуют выбранной аудитории.", 409)
        return snapshot_for(dataset, audience, ideas)
    except (ValueError, TypeError, ContractError) as exc:
        raise DomainError("analytics_unavailable", "Не удалось проверить данные аналитики.", 503) from exc


@transaction.atomic
def import_dataset(payload):
    validate_payload(payload)
    list(AnalyticsDataset.objects.select_for_update().filter(key=KEY).values_list("id", flat=True))
    if AnalyticsDataset.objects.filter(key=KEY, enabled=True, version__gt=payload["version"]).exists():
        raise ValueError("Активна более новая версия набора; понижение версии запрещено.")
    dataset, created = AnalyticsDataset.objects.get_or_create(
        key=KEY, version=payload["version"],
        defaults={"payload": payload, "payload_hash": digest(payload)},
    )
    if dataset.payload_hash != digest(payload) or dataset.payload != payload:
        raise ValueError("Эта версия уже существует с другим содержимым.")
    for audience in AUDIENCES:
        summary(dataset, audience)
    AnalyticsDataset.objects.filter(key=KEY).exclude(pk=dataset.pk).update(enabled=False)
    dataset.enabled = True
    dataset.save(update_fields=["enabled"])
    return dataset, created


def history(snapshot, audience=None):
    if not snapshot:
        return None
    return {
        "source": "demo", "label": snapshot["label"], "audience": snapshot["audience"],
        "dataset_version": snapshot["dataset_version"], "dataset_hash": snapshot["dataset_hash"],
        "period_start": snapshot["period_start"], "period_end": snapshot["period_end"],
        "snapshot_hash": snapshot["snapshot_hash"],
        "ideas": [i["advice"] for i in snapshot["recommendations"]],
        "recommendations": deepcopy(snapshot["recommendations"]),
        "same_audience": audience is None or audience == snapshot["audience"],
    }
