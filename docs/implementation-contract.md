# Контракт реализации mini-games

Рабочий документ команды реализации, 18.10.2026. Ветка `mini-games`; тестовый бюджет
реальной модели — **$50 суммарно**, разрешён пользователем для этой реализации.

## Модули и ответственность

- `gameforge/`, `studio/`, `manage.py`: Django, данные, API, очередь и orchestration.
- `generation/`: независимые от Django схемы, prompt, Codex/vLLM/fake, exact patches, HTML bundler.
- `validation/`: независимая проверка экспортируемого HTML в контейнере без сети/секретов.
- `web/`: React/TS/SCSS клиент. API `/api/`, session+CSRF. UI `/`, `/chats/:id`, `/games/:id`.

## Python interface (обязателен для интеграции)

`generation.service.generate(request: dict, *, on_event: Callable, is_cancelled: Callable) -> dict`
принимает `{operation: create|edit|repair, prompt, audience, preferences, base_revision,
files, design, checks, findings, provider, model}`. Возвращает `{response: {...}, usage:
{input_tokens, cached_input_tokens, output_tokens}, elapsed_seconds, provider, model,
invocation_id}`. Типизированные исключения содержат `code`, `message`, `usage`, `outcome_unknown`.
`on_event` передаёт короткое событие, не секреты; `is_cancelled()` останавливает транспорт.
Сохранение входа/полного ответа и учёт бюджета выполняет Django до переходов.

`generation.artifacts.materialize(response, *, base_revision=None, files=None,
previous_checks=None) -> dict` возвращает `{files, html, artifact_hash, file_hashes,
design, checks, title, diff}` либо исключение контракта. Create содержит файлы, edit/repair
к существующему кандидату — только точные патчи. Schema и примеры лежат в generation.

`validation.service.validate(html: str, checks: list[dict], *, artifact_hash: str) -> dict`
возвращает `{status: passed|failed|unverified|infrastructure_error, findings: [], facts: [],
elapsed_seconds, environment, artifact_hash}`. Выполнение изолировано от Django.
Проверки используют настоящее управление и чтение наблюдений; не принимают игровой
`passed: true`. Генератор и validator согласуют DSL напрямую, до реальных вызовов.

## HTTP (уточняется backend вместе с frontend)

Все ответы JSON, ошибки `{error: {code, message, details?}}`; UUID, даты ISO8601.
GET `/api/session/` выдаёт `{user: null|{id,username}, csrfToken, preferences, capabilities}`.
POST `/api/login/`, `/api/logout/`; CSRF обязателен, клиент отправляет X-CSRFToken.
GET/POST `/api/chats/`; GET/DELETE `/api/chats/:id/`; POST `/api/chats/:id/runs/`
с `{prompt,audience,idempotency_key}`. Состояния запуска и доступные действия возвращает API.
POST `/api/runs/:id/cancel/`, `/continue/`, `/confirm/`; GET `/api/runs/:id/` и
GET `/api/runs/:id/events/?after=ID` (SSE, persisted ID, reconnect).
Версии/история, экспорт, диагностические подробности и preview URL — через владельца чата.
GET/POST `/api/publications/`, PATCH/DELETE `/api/publications/:id/`, POST `/like/`, `/remix/`.
GET/PATCH `/api/preferences/`, POST `/api/chats/:id/feedback/`.

Preview использует другой origin и непривилегированный sandbox. URL подписан для конкретного
неизменяемого артефакта; скачивание/публикация/preview используют одни байты.
Последняя рабочая версия и сохранённый кандидат различаются. Статус `unverified` требует
явного подтверждения человека и не выдаётся за автоматический успех.
