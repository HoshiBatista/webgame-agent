# Контракт реализации mini-games

Рабочий документ команды реализации, 18.10.2026. Ветка `mini-games`; тестовый бюджет
реальной модели — **$50 суммарно**, разрешён пользователем для этой реализации.

## Модули и ответственность

- `gameforge/`, `studio/`, `manage.py`: Django, данные, API, очередь и orchestration.
- `generation/`: независимые от Django схемы, prompt, Codex/vLLM/fake, exact patches, HTML bundler.
- `validation/`: независимая проверка экспортируемого HTML в контейнере без сети/секретов.
- `web/`: React/TS/SCSS клиент. API `/api/`, session+CSRF. UI `/`, `/chats/:id`, `/games/:id`,
  приватный проигрыватель `/play/:revisionId` для отдельной вкладки.

## Python interface (обязателен для интеграции)

`generation.service.generate(request: dict, *, on_event: Callable, is_cancelled: Callable) -> dict`
принимает `{operation: create|edit|repair, prompt, audience, preferences, base_revision,
files, design, checks, findings, provider, model, execution_limits?}`. Для vLLM пределы
контекста и `max_output_tokens` обязательны; backend берёт их из конфигурации тарифов,
адаптер ограничивает вход до отправки и передаёт максимум выхода в API. Возвращает `{response: {...}, usage:
{input_tokens, cached_input_tokens, output_tokens}, elapsed_seconds, provider, model,
invocation_id}`. Типизированные исключения содержат `code`, `message`, `usage`, `outcome_unknown`.
`on_event` передаёт короткое событие, не секреты; `is_cancelled()` останавливает транспорт.
Сохранение входа/полного ответа и учёт бюджета выполняет Django до переходов.

`generation.artifacts.materialize(response, *, operation, base_revision=None, files=None,
previous_checks=None) -> dict` возвращает `{files, html, artifact_hash, file_hashes,
design, checks, title, diff}`, нейтральный `{status: unchanged, message}` либо исключение
контракта. `operation` берётся из сохранённого доверенного запроса; ответ модели должен
совпасть с ним. Create содержит файлы, edit/repair к существующему кандидату — только
точные патчи. Edit может обновить игровые требования; repair сохраняет требования
материализованного кандидата. Неизменённые проверки наследуются. Пустое `ok` отклоняется
как `no_changes`; явное `unchanged` не создаёт новую версию. Schema и примеры — в generation.

`validation.service.validate(html: str, checks: list[dict], *, artifact_hash: str) -> dict`
возвращает `{status: passed|failed|unverified|infrastructure_error, findings: [], facts: [],
elapsed_seconds, environment, artifact_hash}`. Выполнение изолировано от Django.
Проверки используют настоящее управление и чтение наблюдений; не принимают игровой
`passed: true`. Генератор и validator согласуют DSL напрямую, до реальных вызовов.

## HTTP

Полный реализованный контракт: [api.md](api.md).

Обычные данные API — JSON, ошибки `{error: {code, message, details?}}`. Исключения:
events — SSE, export/preview — HTML, thumbnail — изображение, успешный DELETE — пустой 204.
Идентификаторы чатов/запусков/версий/публикаций — UUID; User, Feedback и события имеют
числовые ID. Даты — ISO8601.
GET `/api/session/` выдаёт `{user: null|{id,username,is_staff}, csrfToken, preferences,
capabilities, budget}`. У гостя `budget:null`; у вошедшего — общий лимит, подтверждённый
расход, активный резерв, неизвестный расход и доступная сумма. Каталог `capabilities.models`
содержит доступность настроенного тарифа (`priced`), а не обещание доступного бюджета.
POST `/api/login/`, `/api/logout/`; CSRF обязателен, клиент отправляет X-CSRFToken.
GET/POST `/api/chats/`; GET/DELETE `/api/chats/:id/`; POST `/api/chats/:id/runs/`
с `{prompt,audience?,model?,idempotency_key}`. Состояния запуска и доступные действия возвращает API.
POST `/api/runs/:id/cancel/`, `/continue/`, `/confirm/`; GET `/api/runs/:id/` и
GET `/api/runs/:id/events/?after=ID` (SSE, persisted ID, reconnect).
При продолжении по умолчанию сохраняются provider/model исходного запуска.
POST `/api/chats/:id/restore/` с `{revision_id}` выбирает принятую историческую версию без модели.
Версии/история, экспорт, диагностические подробности и preview URL — через владельца чата.
GET/POST `/api/publications/`, GET/PATCH/DELETE `/api/publications/:id/`,
PUT `/like/` (POST также поддерживается), POST `/remix/`, GET `/thumbnail/`.
GET/PATCH `/api/preferences/`, POST `/api/chats/:id/feedback/`.

Preview использует другой origin и непривилегированный sandbox. URL подписан для конкретного
неизменяемого артефакта; скачивание/публикация/preview используют одни байты.
Последняя рабочая версия и сохранённый кандидат различаются. Статус `unverified` требует
явного подтверждения человека и не выдаётся за автоматический успех.
Fullscreen сохраняет существующий iframe; сворачивание всей панели preview его размонтирует,
поэтому повторное открытие начинает игру заново, не меняя сохранённую версию.
