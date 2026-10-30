"""One bounded, immutable interpretation of a scenario, shared by all executors.

The wire schema validates shape; this compiler owns types, setup boundaries and
execution cost. It uses only stdlib so the isolated browser imports the same code.
"""

import json
import string
from dataclasses import dataclass

from .checks import (
    EXPERIENCE_BOOLEANS,
    EXPERIENCE_FIELDS,
    EXPERIENCE_NUMBERS,
    INPUT,
    NUMERIC,
    ORDERED,
    RELATIVE,
    numeric,
    review_checks,
)
from .contracts import VIEWPORTS

# Deliberately bounded keyboard vocabulary, shared by both providers. These are
# physical US-layout keys supported by the pinned Playwright browser; arbitrary
# Unicode text is not a physical key and must not become an infrastructure error.
KEYS = set(string.ascii_letters + string.digits + string.punctuation + ' ') | {
    'Enter', 'Tab', 'Escape', 'Space', 'Backspace', 'Delete', 'Insert', 'Home', 'End',
    'PageUp', 'PageDown', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    'Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'NumLock', 'ScrollLock', 'Pause',
    'Backquote', 'Minus', 'Equal', 'Backslash', 'BracketLeft', 'BracketRight',
    'Semicolon', 'Quote', 'Comma', 'Period', 'Slash',
} | {f'Key{x}' for x in string.ascii_uppercase} | {f'Digit{x}' for x in string.digits} | {
    f'F{x}' for x in range(1, 13)
} | {f'{key}{side}' for key in ('Shift', 'Control', 'Alt', 'Meta') for side in ('Left', 'Right')}


def supported_key(key, action):
    if key in KEYS:
        return True
    if not isinstance(key, str) or action != 'press':
        return False
    parts = key.split('+')
    return (len(parts) > 1 and parts[-1] in KEYS and len(set(parts[:-1])) == len(parts) - 1
            and all(p in {'Shift', 'Control', 'Alt', 'Meta', 'ControlOrMeta'} for p in parts[:-1]))


@dataclass(frozen=True)
class CheckIssue:
    code: str
    field: str
    message: str


@dataclass(frozen=True)
class CheckProgram:
    encoded: str
    measured_from: int
    wait_ms: int
    relative: bool
    issue: CheckIssue | None = None

    def without_last_input(self):
        """Preserve setup; omit the last measured input and its matching release."""
        if self.issue:
            return None
        check = self.check()
        if check["category"] not in {"control", "outcome"}:
            return None
        steps, meaningful = check["steps"], []
        pressed: set[str | None] = set()
        for i in range(self.measured_from, len(steps)):
            step = steps[i]
            kind, key = step.get("action"), step.get("key")
            if kind == "key_up" and key in pressed:
                pressed.remove(key)
                continue
            if kind == "key_down":
                pressed.add(key)
            if kind in INPUT:
                meaningful.append(i)
        if not meaningful:
            return None
        index = meaningful[-1]
        if steps[index]['action'] == 'hold_touch':
            # Keep elapsed time identical: a timer-only effect must not be
            # mistaken for a response to holding the finger on a control.
            return {**check, 'steps': [({'action': 'wait', 'ms': s['ms']} if i == index else s)
                                       for i, s in enumerate(steps)],
                    '_without_input': True, '_omitted': [index]}
        omitted = {index}
        if steps[index]["action"] == "key_down":
            # Omit only the first matching release of this measured key press.
            release = next((i for i in range(index + 1, len(steps))
                            if steps[i].get("action") == "key_up" and steps[i].get("key") == steps[index].get("key")), None)
            if release is not None:
                omitted.add(release)
        return {**check, "steps": [s for i, s in enumerate(steps) if i not in omitted],
                "_without_input": True, "_omitted": sorted(omitted)}

    def check(self):
        return json.loads(self.encoded)

    @property
    def wait_seconds(self):
        return (sum(s.get('ms', 0) for s in self.check()['steps']) + 40) / 1000


def envelope(checks):
    if not isinstance(checks, list) or len(checks) > 12:
        raise ValueError('invalid browser check count')
    # Bound traversal before semantic work; no arbitrary nested tool input.
    if len(json.dumps(checks, ensure_ascii=True, allow_nan=False)) > 200_000:
        raise ValueError('browser checks exceed size limit')
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get('steps'), list) or len(check['steps']) > 30:
            raise ValueError('invalid browser steps')
        for step in check['steps']:
            if not isinstance(step, dict) or type(step.get('ms', 0)) is not int or not 0 <= step.get('ms', 0) <= 10000:
                raise ValueError('invalid browser action or wait')


def compile_check(check, *, timer_outcome=False):
    envelope([check])
    def malformed(field):
        return CheckProgram(json.dumps(check), 0, 40, False,
                            CheckIssue('invalid_check', field, 'Некорректный тип поля сценария: ' + field))
    for field in ('id', 'category', 'viewport', 'requirement'):
        if not isinstance(check.get(field), str):
            return malformed(field)
    for field in ('observation', 'expect'):
        if not isinstance(check.get(field), dict):
            return malformed(field)
        for key, value in check[field].items():
            if key != 'value' and not isinstance(value, str):
                return malformed(field + '.' + str(key))
    for step in check['steps']:
        for field in ('action', 'selector', 'key'):
            if field in step and step[field] is not None and not isinstance(step[field], str):
                return malformed('steps.' + field)
    if not isinstance(check['expect'].get('operator'), str):
        return malformed('expect.operator')
    effective, _ = review_checks([check])
    check = effective[0]
    encoded = json.dumps(check, ensure_ascii=True, sort_keys=True, allow_nan=False)
    steps = check['steps']
    checkpoints = [i for i, s in enumerate(steps) if s.get('action') == 'checkpoint']
    awaits = [i for i, s in enumerate(steps) if s.get('action') == 'wait_for']
    measured_from = checkpoints[0] + 1 if checkpoints else 0
    observation, expect = check.get('observation', {}), check.get('expect', {})
    source, op, value = observation.get('source'), expect.get('operator'), expect.get('value')

    def result(code='', field='', message=''):
        return CheckProgram(encoded, measured_from, steps[-1].get('ms', 40) if awaits and awaits[-1] == len(steps)-1 else 40,
                            op in RELATIVE, CheckIssue(code, field, message) if code else None)

    if check.get('viewport') not in VIEWPORTS or check.get('category') not in {'start','control','outcome','restart','regression'}:
        return result('invalid_check', 'category', 'Неизвестная категория или размер экрана.')
    if any(str(k).startswith('_') for k in check):
        return result('invalid_check', 'steps', 'Служебные поля не входят в сценарий.')
    if len(checkpoints) > 1:
        return result('invalid_check', 'steps', 'Допустима одна граница checkpoint между подготовкой и измеряемым вводом.')
    if sum(s.get('ms', 0) for s in steps) > 10000:
        return result('long_check', 'steps', 'Один smoke-сценарий может ожидать не более 10 секунд.')
    if len(awaits) > 1 or awaits and awaits[0] != len(steps)-1:
        return result('invalid_check', 'steps', 'wait_for допустим один раз, последним действием сценария.')
    if check.get('category') in {'control', 'outcome', 'restart'} and not (timer_outcome and check['category'] == 'outcome'):
        if op == 'unchanged' and check['category'] != 'restart':
            return result('invalid_check', 'expect.operator', 'Отсутствие изменения относится к регрессии, а не доказывает основное управление или исход.')
        if not any(s.get('action') in INPUT for s in steps[measured_from:]):
            return result('no_real_input', 'steps', 'После подготовки сценарий должен выполнять настоящий игровой ввод.')
    if op not in RELATIVE | ORDERED | {'eq', 'not_eq', 'contains', 'visible'}:
        return result('invalid_check', 'expect.operator', 'Неизвестный оператор сравнения.')
    if op in ORDERED and not numeric(value):
        return result('invalid_check', 'expect.value', 'Порог сравнения должен быть конечным числом.')
    if source not in {'state', 'text', 'attribute', 'text_number', 'attribute_number', 'experience'}:
        return result('invalid_check', 'observation.source', 'Неизвестный вид наблюдения.')
    if source == 'experience':
        field = observation.get('field')
        if check['category'] in {'start', 'outcome', 'restart'}:
            return result('invalid_check', 'observation', 'Начало, исход и повтор проверяются по игре, а не проигрывателю.')
        if field not in EXPERIENCE_FIELDS:
            return result('invalid_check', 'observation.field', 'Неизвестное наблюдение проигрывателя.')
        if op == 'visible' or (field in EXPERIENCE_NUMBERS and
                              (op == 'contains' or op in {'eq', 'not_eq'} and not numeric(value))) or (
            field in EXPERIENCE_BOOLEANS and (op in NUMERIC or op == 'contains'
                                             or op in {'eq', 'not_eq'} and type(value) is not bool)):
            expected_type = 'числовое' if field in EXPERIENCE_NUMBERS else 'логическое true/false'
            detail = ' graphicsReady — количество загруженных изображений, не признак готовности.' if field == 'graphicsReady' else ''
            return result('invalid_check', 'expect',
                          f'Наблюдение проигрывателя {field} требует {expected_type} ожидание и совместимый оператор.' + detail)
        if field in {'state', 'audioError'} and (op in NUMERIC or op in {'eq', 'not_eq'} and not isinstance(value, str)):
            return result('invalid_check', 'expect', 'Это наблюдение проигрывателя требует строковое ожидание.')
    if source == 'state' and any(p.lower() in {'__proto__','constructor','prototype','passed','testpassed','test_passed'}
                                 for p in observation.get('path', '').split('.')):
        return result('self_report_check', 'observation.path', 'Проверяйте игровой эффект, а не игровой самоотчёт passed.')
    if source in {'attribute', 'attribute_number'} and observation.get('attribute', '').lower() in {
        'data-passed', 'passed', 'data-test-passed',
    }:
        return result('self_report_check', 'observation.attribute', 'Проверяйте игровой эффект, а не атрибут самоотчёта.')
    for step in steps:
        kind = step.get('action')
        if kind not in INPUT | {'checkpoint','wait_for','wait','blur','resize', 'await_condition', 'assert'}:
            return result('invalid_check', 'steps', 'Неизвестное действие.')
        if kind in {'await_condition', 'assert'}:
            if kind == 'assert' and step.get('ms') != 0:
                return result('invalid_check', 'steps.ms', 'assert проверяется сразу; для ожидания используйте await_condition.')
            # Compile a leaf assertion with the same rules; nested programs are
            # impossible because it has no steps. All waits count in this route.
            leaf = {**check, 'category': 'regression', 'steps': [],
                    'observation': step.get('observation'), 'expect': step.get('expect')}
            issue = compile_check(leaf).issue
            if issue:
                return result(issue.code, 'steps.' + issue.field, issue.message)
            if step['expect']['operator'] in RELATIVE:
                return result('invalid_check', 'steps.expect', 'Промежуточное условие требует абсолютное сравнение; относительное оставьте финальному checkpoint.')
        if kind == 'hold_touch' and (check['viewport'] == 'desktop' or type(step.get('ms')) is not int
                                     or not 1 <= step['ms'] <= 3000):
            return result('invalid_check', 'steps', 'Удержание касания требует сенсорный экран и длительность 1–3000 мс.')
        if kind in {'click','tap', 'hold_touch'} and ((step.get('x') is None) != (step.get('y') is None)
                                      or not step.get('selector') and step.get('x') is None):
            return result('invalid_pointer', 'steps', 'Укажите selector или обе координаты действия.')
        if kind in {'click', 'tap', 'hold_touch', 'click_fraction', 'tap_fraction'}:
            if any(v is not None and not numeric(v) for v in (step.get('x'), step.get('y'))):
                return result('invalid_pointer', 'steps', 'Координаты должны быть конечными числами.')
        if kind in {'click_fraction', 'tap_fraction'} and (
            not step.get('selector') or any(not numeric(v) or not 0 <= v <= 1 for v in (step.get('x'), step.get('y')))
        ):
            return result('invalid_pointer', 'steps', 'Доли координат требуют selector и x/y от 0 до 1.')
        if kind in {'press', 'key_down', 'key_up'} and not supported_key(step.get('key'), kind):
            return result('invalid_check', 'steps.key', 'Неподдерживаемая физическая клавиша. Используйте ArrowUp/Down/Left/Right, Space или клавиши латинской раскладки.')
        if kind == 'resize' and step.get('viewport') not in VIEWPORTS:
            return result('invalid_check', 'steps.viewport', 'Неизвестный размер контрольного viewport.')
    if op in NUMERIC and source in {'text', 'attribute'}:
        return result('invalid_check', 'observation.source', 'Числовое сравнение требует числовое наблюдение.')
    if source in {'text_number','attribute_number'} and (op in {'contains','visible'} or op in {'eq','not_eq'} and not numeric(value)):
        return result('invalid_check', 'expect', 'Числовое наблюдение требует числовое сравнение.')
    if source in {'text','attribute'} and op in {'eq','not_eq'} and not isinstance(value,str):
        return result('invalid_check', 'expect.value', 'Текстовое наблюдение требует строковое ожидание.')
    if op == 'contains' and (not isinstance(value,str) or not value.strip()):
        return result('trivial_expectation', 'expect.value', 'Ожидание contains требует непустую строку.')
    if op == 'visible' and source == 'state':
        return result('invalid_check', 'observation.source', 'Видимость проверяется по элементу страницы; для state используйте eq.')
    return result()


def compile_suite(checks, *, timer_ids=frozenset()):
    envelope(checks)
    return tuple(compile_check(check, timer_outcome=check.get('id') in timer_ids) for check in checks)
