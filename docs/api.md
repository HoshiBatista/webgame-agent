# Mini-games HTTP API

All authenticated mutation requests require the CSRF token from `GET /api/session/` in `X-CSRFToken` and session cookies. Errors are `{error:{code,message,details?}}`. Chat/run/revision/publication IDs are UUIDs; user, feedback and event IDs are numeric. ISO timestamps. Normal data responses are JSON; events are SSE, export and preview return HTML, thumbnails return images, and successful DELETE returns empty 204. List endpoints return `{results:[...]}`. Server URLs below include trailing slash.

Generation always runs in Celery, never in the submitting HTTP request. A run and its
delivery outbox are committed together before `202`. Closing the browser or its SSE
stream does not cancel the run. After reconnect/login, read the same owned chat/run
and its saved revision; replay events with `Last-Event-ID`. If the submission response
was lost, reusing the exact payload and `idempotency_key` returns the existing run.
Do not create a new key or inference automatically on network failure. Only explicit
cancel/delete actions cancel work. Worker crashes and upstream disconnects after a
model request was sent are separate, potentially unknown outcomes.

- `GET /api/session/`: `{user:null|{id,username,is_staff},csrfToken,preferences:{theme,notes},capabilities:{provider,model,models,local_only},budget:null|{limit_usd,spent_usd,reserved_usd,unknown_usd,available_usd}}`. Guest budget is null. Model catalog entries include `{id,name,priced}`; `priced` means a tariff is configured, not that sufficient budget is available.
- `POST /api/login/`: `{username,password}` → session response. `POST /api/logout/` → `{ok:true}`.
- `GET /api/chats/`: owned chat summaries `{id,title,audience,updated_at,current_revision,active_run}`.
- `POST /api/chats/`: optional `{title,audience}` → full chat. Empty title allowed. `GET /api/chats/:id/` → `{id,title,audience,created_at,updated_at,current_revision:Revision|null,candidate_revision:Revision|null,messages:Message[],revisions:Revision[],runs:Run[],active_run:Run|null,source_publication:null|uuid}`. `DELETE` → 204. Publications survive deletion.
- `POST /api/chats/:id/runs/`: `{prompt,audience?,model?,idempotency_key}` → `Run` (202). Same idempotency key returns the same run, conflicting payload rejected. `GET /api/runs/:id/` → `Run`.
- `POST /api/runs/:id/cancel/`: cancel even in flight; preserves accepted version. `POST /api/runs/:id/continue/`: optional `{prompt,idempotency_key,accept_unknown_cost}` resumes saved candidate/last exact response; does not replay planning. Provider and model default to those of the original run. An unresolved unknown invocation requires explicit boolean `accept_unknown_cost:true` for a new attempt. The old liability remains untouched, the new invocation is accounted separately, and the accepted revision must still match the original base (`retry_base_changed` otherwise). The same idempotency key and payload return the same new run; no automatic retry/reconciliation is implied.
- `POST /api/runs/:id/confirm/`: `{confirmed:true}` accepts an unverified candidate with explicit human verification; failed/infrastructure-error candidates cannot be manually marked green.
- `GET /api/runs/:id/events/?after=ID`: finite SSE stream of persisted events (client reconnects); events have increasing integer `id`, `event:progress`, `data:{id,kind,message,created_at,details}`. Each reconnect uses Last-Event-ID or after. `GET /api/runs/:id/diagnostics/` private request/response/errors/reports only for owner. New invocations retain `request.generation_contract.{system_prompt_sha256,response_schema_sha256}`, `provider_invocation_id` (actual provider turn/request ID when reported) and `provider_metadata` (thread/turn/request IDs and separate local execution ID). These identifiers are not exposed in normal run/events/publication responses; absent provider IDs are never invented.
- `POST /api/chats/:id/restore/`: `{revision_id}` selects an accepted historical revision when no run is active; no model call.
- `GET /api/revisions/:id/`: private revision summary. `GET /api/revisions/:id/export/`: exact single HTML download; same bytes used by preview. `GET /api/revisions/:id/preview/`: `{url}` signed URL on separate preview origin. Optional `GET /api/revisions/:id/source/` for owner source diagnostics.
- `GET /api/publications/?sort=new|popular&mine=1`: authenticated feed. `POST /api/publications/`: `{chat_id,title,revision_id?}` → Publication. Revision must be accepted in owned chat. `GET /api/publications/:id/`: published data; public read-only allowed. `PATCH`: owner `{title?,revision_id?}`; updating revision explicit and immutable snapshot stays until then. `DELETE`: owner only. `PUT /api/publications/:id/like/`: `{liked:true|false}` → `{liked,likes}` (POST supported too). `POST /api/publications/:id/remix/` → new own full chat, published revision copied, source prompts excluded.
- `GET /api/publications/:id/thumbnail/`: a saved validator screenshot for the published revision, if available; image response, not generated illustration. Public read allowed.
- `GET/PATCH /api/preferences/`: `{theme:light|dark,notes:string[]}`. `POST /api/chats/:id/feedback/`: `{rating:1..5,reasons?:string[]}` → feedback; reasons added to editable preference notes, no model call.
- `GET /api/health/`: health liveness; no secrets.

`Message`: `{id,role:user|assistant|system,content,created_at,run_id}`.

`Revision`: `{id,title,number,artifact_hash,design,checks,created_at,accepted,verification:automatic|manual|none,preview_url,export_url,parent_id,report:{status,findings,facts,elapsed_seconds}|null}`. Source files are only returned by private source/diagnostics endpoints. Candidate may be previewed safely but is not accepted/publishable.

`Run`: `{id,chat_id,operation,status,stage,message,prompt,created_at,updated_at,finished_at,base_revision_id,candidate_revision_id,result_revision_id,error:{code,message,details}|null,can_cancel,can_continue,can_retry_unknown,can_confirm,attempts,max_repair_attempts,max_model_calls,elapsed_seconds,events_url,budget,metrics}`. Statuses `queued`, `generating`, `checking`, `succeeded`, `needs_attention`, `unverified`, `failed`, `cancelled`, `unknown`. `can_continue` is true for `needs_attention`, `unverified`, `failed` and `cancelled` unless that run has an unresolved unknown invocation. `can_retry_unknown` exposes a separately acknowledged new attempt for `unknown` or `cancelled` with an unknown invocation and unchanged base revision. Neither capability guarantees admission: budget and active-chat constraints are checked by the backend again. A budget error alone does not hide the continuation button. `unknown` deliberately cannot blind-retry. `stage/message` are concrete Russian user explanations. No fake percent.

`Publication`: `{id,title,author:{id?,username},created_at,updated_at,revision_id,artifact_hash,preview_url,thumbnail_url:null|string,likes,liked,is_owner,source_chat_id:null|owned_chat_id,verification,public_url}`. Unauthenticated public responses omit author id and return `source_chat_id:null`; only the owner sees an undeleted private source chat ID. Frontend fallback thumbnail is a neutral illustration, not a claimed screenshot. Share URL `/games/:id`; preview shell must use sandbox `allow-scripts` (no allow-same-origin) and no credential propagation. The private player route `/play/:revisionId` requires login and keeps the same isolated iframe boundary.

The API stores a shared app budget. `spent_usd` confirmed usage, `reserved_usd` active calls, `unknown_usd` unresolved sent calls. API-equivalent subscription accounting is not a card invoice. Generation defaults to one model call plus at most one repair. Explicit continuation starts another bounded attempt using saved candidate, never whole-history context.

An edit that reports `ok` but changes neither final source files nor the final check suite is a `no_changes` contract failure and gets the same single corrective attempt as other model contract failures. A provider's explicit `unchanged` result with a valid exact base finishes as `needs_attention` with `error.code=unchanged` and its explanation. It creates no revision, runs no browser check and does not retry automatically. The last accepted game remains selected; prose alone is never treated as evidence of an implemented edit.

## API сохраняемой очереди модели

Отдельный сервис `llm-relay`, HTTPS origin реле. Он не заменяет сессионный Django API.
Все маршруты `/bridge/v1/*`, включая health, требуют Bearer-токен. У `client` и `worker`
разные роли. Client видит только задания своего principal; GameForge дополнительно проверяет
владельца чата. Токены и ответы не передаются в URL или обычные журналы.

| Метод и путь | Роль | Назначение |
| --- | --- | --- |
| GET `/bridge/v1/health` | обе | Проверка очереди без вызова GPU |
| PUT `/bridge/v1/jobs/{uuid}` | client | `{"payload": chat_completions_payload}`; идемпотентное принятие |
| GET `/bridge/v1/jobs/{uuid}` | client | Состояние, cancel_requested, подтверждённый receipt и его SHA-256 |
| POST `/bridge/v1/jobs/{uuid}/cancel` | client | Сохраняемая отмена; до submit создаёт запрещающую поздний запуск запись |
| POST `/bridge/v1/worker/claim` | worker | `{}`; одно назначение, повтор возвращает прежнее |
| POST `/bridge/v1/worker/{uuid}/start` | worker | `{}`; подтверждение начала, флаг отмены |
| POST `/bridge/v1/worker/{uuid}/heartbeat` | worker | `{"first_output": true/false}`; состояние и отмена |
| POST `/bridge/v1/worker/{uuid}/receipt` | worker | Сохранённый `{"ok":true,"result":...}` либо `{"ok":false,"error":...}` |

Состояния: `queued`, `assigned`, `running`, затем `completed`, `failed`, `unknown` или
`cancelled`. Потеря heartbeat не переводит задание обратно в очередь. Receipt неизменяем:
повтор тех же данных подтверждается, другие данные дают 409. Неизвестный UUID и чужой UUID
дают 404. Неверная роль — 403, отсутствие/отзыв токена — 401, конфликт payload — 409,
лимит размера — 413, очередь client заполнена — 429, общий предел хранения — 507.

Все успешные операции возвращают 200 и JSON, `Cache-Control: no-store`. До завершения
GET не содержит receipt. Проверка статуса и повтор передачи не считаются новым inference.
JSON результата целиком повторно скачивается после обрыва; это не SSE и не HTTP Range.

Успешный receipt.result.response содержит стандартный Chat Completions envelope, а не
разобранную игру. Сетевые службы передают текст/finish_reason/usage без прикладной проверки;
GameForge разбирает их в своём адаптере. Детали v1 находятся в docs/PROTOCOL.md отдельных служб.


### Поэтапная проверка и исправления (23.10.2026)

В Run добавлены `max_repair_attempts` (фиксированный лимит исправлений) и
`max_model_calls` (первый вызов + лимит). Новые задания получают 2 или 3 исправления
из настройки сервера, по умолчанию 3; после перезапуска лимит не пересчитывается.
Прежние задания сохраняют старый предел. При ожидании ответа relay счётчик не растёт.
`stage=repairing` и message показывают номер текущего исправления.
В `Revision.report` добавлен `stages`: массив `{stage,status}` с дополнительными
диагностическими полями. Этап `syntax` предшествует `browser`; при ошибке разбора
второй этап отсутствует. Старые отчёты имеют пустой список этапов. Эти поля не
заменяют verdict/facts и не разрешают публиковать непроверенную игру.
