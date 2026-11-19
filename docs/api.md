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
- `POST /api/login/`: `{username,password}` → session response. `POST /api/logout/` → `{ok:true,...anonymousSession}` with `user:null`, `budget:null`, empty preference notes and a guest CSRF token. The client can switch directly to the landing without a second session read.
- `GET /api/chats/`: owned chat summaries `{id,title,audience,updated_at,current_revision,active_run}`.
- Requests scoped to a missing, deleted or another user's chat return the same `404` with `error.code=chat_not_found` and a Russian user-facing message. Clients show an unavailable-chat screen with an explicit way to `/chats/new`; observing a 404 must not create a replacement chat or submit generation automatically.
- `POST /api/chats/`: optional `{title,audience}` → full chat. Missing/empty title becomes `Новая игра`; an explicitly supplied nonempty title is treated as a manual choice. `GET /api/chats/:id/` → `{id,title,audience,created_at,updated_at,current_revision:Revision|null,candidate_revision:Revision|null,messages:Message[],revisions:Revision[],runs:Run[],active_run:Run|null,source_publication:null|uuid}`. `PATCH {title}` → full chat; owner only, authenticated session and CSRF required, allowed during generation. Title must be nonempty after whitespace normalization and at most 160 characters. Even saving the same title marks it as manual; clients cannot reset this flag. `DELETE` → 204. Publications survive deletion.
- `POST /api/chats/:id/runs/`: `{prompt,audience?,model?,idempotency_key,source_revision_id?,source_artifact_hash?,source_is_historical?,generation_profile?,source_format?}` → `Run` (202). An existing game requires the exact displayed source UUID/hash; an unaccepted draft is a valid edit source. Stale/foreign sources fail, never silently become create. A deliberately selected older source uses `source_is_historical:true`. `Run.source_revision_id` is separate from the accepted `base_revision_id` used for concurrency checks. Same key and payload return the same run. `generation_profile` is `full|compact`, `source_format` is `string|lines` (lines only for compact). Source/continuation profile is immutable; switching Lite/Pro does not change the artifact format. `GET /api/runs/:id/` → `Run`.
- `POST /api/runs/:id/cancel/`: cancel even in flight; preserves accepted version. `POST /api/runs/:id/continue/`: optional `{prompt,idempotency_key,accept_unknown_cost}` resumes saved candidate/last exact response; does not replay planning. Provider and model default to those of the original run. An unresolved unknown invocation requires explicit boolean `accept_unknown_cost:true` for a new attempt. The old liability remains untouched, the new invocation is accounted separately, and the accepted revision must still match the original base (`retry_base_changed` otherwise). The same idempotency key and payload return the same new run; no automatic retry/reconciliation is implied.
- `POST /api/runs/:id/recheck/`: optional `{idempotency_key}` checks the same saved candidate in a new run with `allow_model_calls=false`. It neither invokes a provider nor materializes pending replies from the original run. Ownership, active-chat and unchanged-base guards apply. Existing unknown model liability is preserved.
- `POST /api/runs/:id/confirm/`: `{confirmed:true,artifact_hash,report_id}` accepts the exact candidate after explicit human verification. Copy evidence tokens from `Run.confirmation`; mismatched tokens, changed validator/base, active work, known gameplay failures or missing mandatory gate receipts reject confirmation. Eligibility is evidence-based, including an otherwise eligible `needs_attention` run. Acceptance remains `manual`.
- `GET /api/runs/:id/events/?after=ID`: finite SSE stream of persisted events (client reconnects); events have increasing integer `id`, `event:progress`, `data:{id,kind,message,created_at,details}`. Each reconnect uses Last-Event-ID or after. `GET /api/runs/:id/diagnostics/` private request/response/errors/reports only for owner. New invocations retain `request.generation_contract.{system_prompt_sha256,response_schema_sha256}`, `provider_invocation_id` (actual provider turn/request ID when reported) and `provider_metadata` (thread/turn/request IDs and separate local execution ID). These identifiers are not exposed in normal run/events/publication responses; absent provider IDs are never invented.
- `POST /api/chats/:id/restore/`: `{revision_id}` selects an accepted historical revision when no run is active; no model call.
- `POST /api/chats/:id/variant-batches/` accepts the ordinary run payload with explicit `model_profile="pro"` and the same source and idempotency rules. A 202 response returns a batch with four independent ordinary runs. The chat detail exposes `variant_batches`. Each slot 1–4 has its own run ID, status, message and playable revision when available. Use the run endpoints for cancellation and review.
- `POST /api/chats/:id/variant-batches/:batch_id/select/` accepts `revision_id`, `artifact_hash` and `expected_current_revision_id` (null for a new game). It returns the updated chat. A selected revision must be a successful result in that batch. The current revision may be selected again idempotently. A conflicting concurrent selection returns 409. Other variants can finish after selection. Their results remain available in version history.
- Creating an ordinary Pro batch for a new game with planning enables player analytics by default. Send `analytics_experiment: false` to disable it for that batch. Edits and batches without a planning step default to disabled. An enabled batch returns `analytics_experiment.status` as `applied` or `insufficient_data` and omits the assigned position. A retry with the field omitted keeps the original setting and assignment, including for older batches. An explicit change requires a new idempotency key.
- `POST /api/chats/:id/variant-batches/:batch_id/draft-choice/` records an opted-in author's explicit selection of a playable draft for editing. The body contains `revision_id` and `artifact_hash`. A successful response is 204. The working revision is preserved. For an opted-in batch both choice endpoints accept `ready_revision_ids`, the list of up to four accepted revisions shown as ready. The server records the first registered choice and counts displayed revisions that match the latest accepted slot results. Clients omitting the list still register the choice, with unknown ready count.
- The studio remembers a draft chosen for editing in the current tab across reloads. The next edit uses its exact `source_revision_id` and `source_artifact_hash`. The accepted working revision stays in the database until a new one is selected or an edit succeeds.
- The owner’s run diagnostics include `timings`. `total_seconds` runs from creation through completion (or now for active runs). `initial_queue_seconds` measures the wait for the first worker. `provider_wall_seconds` counts time with at least one request awaiting a receipt, and `provider_sum_seconds` sums individual requests including overlaps. `calls` lists each sent attempt, its role and offset from run creation. `packaging_seconds` is the recorded time spent on successful packaging, or `null` if unavailable. `validation_wall_seconds` covers persisted browser jobs from enqueue through completion, with each job’s reported queue and execution times in `validations`. A missing measurement is `null`. Operators can read the same breakdown with `python manage.py run_timings RUN_UUID`.
- `GET /api/revisions/:id/`: private revision summary. `GET /api/revisions/:id/export/`: exact single HTML download. `GET /api/revisions/:id/preview/`: `{url}` signed URL on separate preview origin; by default the preview serves the same bytes. Adding `audio_control=1` to that signed URL inserts the application's audio-control prelude before the game scripts; stored HTML, hash and export remain unchanged. Controls accept parent-origin messages for this exact artifact only; the preview keeps its existing CSP and opaque sandbox. Optional `GET /api/revisions/:id/source/` for owner source diagnostics.
- `GET /api/publications/?sort=new|popular&mine=1`: authenticated feed. `POST /api/publications/`: `{chat_id,title,revision_id?}` → Publication. Revision must be accepted in owned chat. `GET /api/publications/:id/`: published data; public read-only allowed. `PATCH`: owner `{title?,revision_id?}`; updating revision explicit and immutable snapshot stays until then. `DELETE`: owner only. `PUT /api/publications/:id/like/`: `{liked:true|false}` → `{liked,likes}` (POST supported too). `POST /api/publications/:id/remix/` → new own full chat, published revision copied, source prompts excluded.
- `GET /api/publications/:id/thumbnail/`: a saved validator screenshot for the published revision, if available; image response, not generated illustration. Public read allowed.
- `POST /api/publications/:id/sessions/`: public player bootstrap `{session_id:uuid,token:64-lowercase-hex,revision_id:uuid,artifact_hash:64-lowercase-hex}` → `{session_id,visible_ms,expires_at,analytics}` (201). Guest/authenticated CSRF from `/api/session/` is required. Client generates ID and secret once per iframe load; exact retries return 200 without another opening. Reuse with different identity/secret or a stale publication version returns 409. No player account is required or stored for a play session.
- `PUT /api/publications/:id/sessions/:session_id/` accepts `{token,visible_ms:integer}` and returns session data with the current publication totals. The player sends cumulative visible time every ten seconds and on exit or hide. The server requires the same secret and CSRF, ignores stale or duplicate updates and caps each increment at the smaller of elapsed server time and 15 seconds. Sessions expire after one hour with HTTP 410. Final updates are best-effort, so network loss may undercount duration. The token stays in the player shell.
- Both session endpoints accept the optional `Prefer: return=minimal` header. A successful write or exact retry then returns 204 with an empty body and `Preference-Applied: return=minimal`. The public player uses this option to record activity during play and displays the statistics it read on opening.
- `PUT /api/publications/:id/rating/`: authenticated `{rating:1..5}` → `{average_rating:number,rating_count:number,user_rating:number}`. One editable vote per account/publication. This never invokes a model or modifies creator feedback/preferences. Feed `sort=popular` orders by mean rating descending (unrated last), vote count descending, then newest. Legacy like records/endpoints remain available but are not used by the UI.
- `GET/PATCH /api/preferences/`: `{theme:light|dark,notes:string[],model_profile}`. Template selection is manual; account preferences do not contain a template-suggestion flag. The text `notes.join('\n')` is limited to 3000 Unicode code points, including spaces/newlines; there is no per-line or line-count limit. Leading/trailing whitespace is trimmed after validation; internal paragraphs are preserved. Existing lists remain readable.
- `POST /api/chats/:id/feedback/`: `{rating:1..5,reasons?:string[]}` → feedback including `preferences` and `preferences_full:boolean`; whole new reasons are added only while notes fit 3000 characters. Existing notes are never evicted. Skipped additions remain in the saved feedback and set `preferences_full=true`; no model call.
- `GET/POST /api/templates/`: list or create personal prompt templates. Optional GET `q` filters titles. POST requires `{title,description}`: 1–50 and 1–3000 Unicode code points respectively; whitespace-only values are invalid. Response item is `{id,title,description,created_at,updated_at}`, with a UUID id and ISO dates.
- `GET/PATCH/DELETE /api/templates/:id/`: read, edit either/both text fields or delete an owned template. Missing/foreign UUIDs return 404. All template endpoints require authentication; mutation requires CSRF. Creation returns 201, deletion 204. These endpoints never create chats, games or model calls.
- `GET /api/health/`: health liveness; no secrets.

`Message`: `{id,role:user|assistant|system,content,created_at,run_id}`.

Chat naming makes no additional model calls. On a new automatically named chat,
the first run uses a normalized provisional label of 1–3 words (at most 48 characters). Later prompts do not replace this provisional
name. Saving the first generated candidate refines the label from its model title; acceptance
keeps the same short-name rule. Manually named chats are never renamed automatically.
Renaming and result acceptance lock the same chat row; a late result cannot replace
a manual name. Publication titles and revision/game content are unaffected.
Migration `0011_chat_titles` preserves existing nonempty names as manual choices
because their original provenance is unavailable; empty names get the default.

`Message`: `{id,role,content,created_at,run_id,generation}`. Assistant messages include `generation:{id,status,model_profile,elapsed_seconds}` even when their run is outside the latest 30 entries in `Chat.runs`; messages without a run and user messages have `generation:null`. Cancellation stores one assistant reply, so later requests do not erase the stop from the conversation.

For a new composer request following an unknown outcome, `POST /api/chats/:id/runs/` also accepts `acknowledge_unknown_run_id` and explicit boolean `accept_unknown_cost:true`. The referenced run must belong to this chat and have an unresolved unknown invocation. Consent records the exact invocation IDs and preserves their liability. This starts a new create/edit using the displayed source UUID/hash, audience and prompt; it does not inherit the old continuation's source or replay a saved reply. These fields participate in idempotency. The existing `/continue/` endpoint retains its saved-candidate semantics.

`Revision`: `{id,title,number,artifact_hash,design,checks,created_at,accepted,verification:automatic|manual|none,preview_url,export_url,parent_id,report:{status,findings,facts,elapsed_seconds}|null}`. Source files are only returned by private source/diagnostics endpoints. Candidate may be previewed safely but is not accepted/publishable.

`Run`: `{id,chat_id,operation,status,stage,message,prompt,created_at,updated_at,finished_at,base_revision_id,candidate_revision_id,result_revision_id,error:{code,message,details}|null,can_cancel,can_continue,can_retry_unknown,can_confirm,can_recheck,confirmation,attempts,max_repair_attempts,max_model_calls,elapsed_seconds,events_url,budget,metrics}`. Statuses `queued`, `generating`, `checking`, `succeeded`, `needs_attention`, `unverified`, `failed`, `cancelled`, `unknown`. `can_continue` is true for repairable `needs_attention`, `failed` and `cancelled` runs without unacknowledged unknown invocations in their continuation chain; check-review results do not offer code repair. `can_recheck` offers a provider-free check of a current candidate. `confirmation` is null or `{artifact_hash,report_id,requirements:string[]}` for eligible manual verification. `can_retry_unknown` exposes a separately acknowledged new attempt for terminal `unknown`, `cancelled`, `needs_attention`, `failed` or `unverified` runs with an unacknowledged unknown invocation and unchanged base revision. Rechecks preserve that requirement. Consent records exact invocation IDs, persists through later rechecks and does not cover a subsequent unknown call. Neither capability guarantees admission: budget, prior in-flight calls and active-chat constraints are checked by the backend again. A budget error alone does not hide the continuation button. `unknown` deliberately cannot blind-retry. `stage/message` are concrete Russian user explanations. No fake percent.

`Publication`: `{id,title,author:{id?,username},created_at,updated_at,revision_id,artifact_hash,preview_url,thumbnail_url:null|string,likes,liked,is_owner,source_chat_id:null|owned_chat_id,verification,public_url}`. Unauthenticated public responses omit author id and return `source_chat_id:null`; only the owner sees an undeleted private source chat ID. Frontend fallback thumbnail is a neutral illustration, not a claimed screenshot. Share URL `/games/:id`; preview shell must use sandbox `allow-scripts` (no allow-same-origin) and no credential propagation. The private player route `/play/:revisionId` requires login and keeps the same isolated iframe boundary.

Publication responses also include `average_rating:number|null`, `rating_count:number`, `user_rating:number|null` and `analytics:{opens:number,average_duration_seconds:number|null,successful_completions:number|null}`. An unrated game has a null average and zero votes. Every opening counts once. Average duration includes the full credited visible time of each session that has reached 30 seconds, including ongoing sessions. It is null until the first qualifying session. The same calculation applies to saved sessions. Successful completions remain null in this release and render as an em dash.

The API stores a shared app budget. `spent_usd` confirmed usage, `reserved_usd` active calls, `unknown_usd` unresolved sent calls. API-equivalent subscription accounting is not a card invoice. Generation allows one model call plus up to the frozen 2–3 repairs, and stops earlier on uncertainty, repeated failure or regression under completion policy 2. Explicit continuation uses the saved candidate and rechecks uncertain evidence before considering another model call; it never uses whole-history context.

An explicit continuation searches saved complete replies through intermediate rechecks before requesting a new inference. Only a reply to its exact candidate base is eligible; source-restart audit events stop reuse of superseded replies. Recheck itself never applies a pending model reply. The worker checks unresolved ancestor delivery/consent again before reserving a model call (`outcome_pending` / `outcome_unknown`); an existing receipt and its original usage remain attached to the original invocation.

An edit that reports `ok` but changes neither final source files nor the final check suite is a `no_changes` contract failure and uses the same saved repair budget as other model contract failures. A provider's explicit `unchanged` result with a valid exact base finishes as `needs_attention` with `error.code=unchanged` and its explanation. It creates no revision, runs no browser check and does not retry automatically. The last accepted game remains selected; prose alone is never treated as evidence of an implemented edit.

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

Для ограниченных пилотов create/continue дополнительно принимают `model_call_limit`
(целое 1–4, включая основной вызов) и `model_call_deadline` (ISO-время с часовым поясом).
Они входят в идемпотентный payload и сохраняются в Run. Эффективный `max_model_calls`
равен меньшему из обычного потолка и переданного лимита. Истёкший срок блокирует новый
inference до резервации и непосредственно перед отправкой; получение квитанции уже
отправленного запроса остаётся доступным. Срок не гарантирует отмену удалённого inference:
оператор пилота отдельно отменяет активный Run по общему времени. Run возвращает
`model_call_deadline` или null. Owner-диагностика содержит времена created/sent/finished
каждого Invocation, completion_policy и до 200 событий с признаком усечения.
`stage=repairing` и message показывают номер текущего исправления.
В `Revision.report` добавлен `stages`: массив `{stage,status}` с дополнительными
диагностическими полями. Этап `syntax` предшествует `browser`; при ошибке разбора
второй этап отсутствует. Старые отчёты имеют пустой список этапов. Эти поля не
заменяют verdict/facts и не разрешают публиковать непроверенную игру.

### Контракт исходников v5 (24.10.2026)

Это внутренний контракт worker/model; обычные HTTP-запросы чата не получают новых прав.
`incomplete_sources` означает отсутствие локального исходника или исполняемой реализации
при создании. Ответ/usage сохраняются, Revision ещё нет; следующий шаг остаётся create
в общем лимите. При исчерпании лимита вызовов Run получает конечный needs_attention с этой
причиной. Явное новое продолжение старой непринятой заглушки без рабочей базы может
создать игру заново с событием source_restart и сохранением предыдущей истории.
Recheck остаётся без inference и не выполняет этот переход.

В repair v5 приложение может сохранить в Invocation.request.module_repair разрешённый
файл/hash и предел 12288 байт UTF-8. Альтернатива точным заменам — единственная запись
`{action:"replace_module",path,file_hash,content}` в patches. Старые v2/v3/v4 и обычный edit
эту запись не принимают. HTML, неразрешённый/нетронутый рабочий файл, неверная база/hash,
превышение размера и смешивание с другими патчами запрещены. Checks наследуются точно.
Права формируются приложением; параметр клиента не может их расширить.

### Receipt handling and artifact evidence v7

The HTTP routes are unchanged. A run waiting for an admitted relay job stays active
until the saved receipt is handled; polling does not consume another model call.
The model-call deadline blocks new submissions, but not collection of existing receipts.
Direct transports with an unknown submitted outcome require reconciliation/explicit retry.
Unsent reservations also survive direct-provider recovery with the same request and UUID.
They retain their reservation until sending or cancellation; deadlines still block sending.

Reports include `assessment.artifact_evidence` when produced by the new validator:
version 1, artifact hash, environment, syntax result/script count and per-viewport
load/error/surface evidence. It is independent of scenario completeness. Positive
artifact gates alone never mean that gameplay requirements passed. Empty or incomplete
requirements do not enable `can_confirm`. Revised model scenarios retain explicit review.
Findings may contain a bounded `diagnostic` from the game frame (observed types,
failed step, controls and geometry); no full DOM or host data is exposed.
Every shortening sets `diagnostic.truncated`, including nested values and feedback limits.
For an uncovered viewport, `artifact_evidence.viewports[].probes` records any replay of
already successful real inputs. Replays supply artifact evidence only. A
`surface_not_observed` finding means missing scenario evidence, not infrastructure failure;
it can permit one source-preserving check repair with verified loading evidence, but
cannot enable confirmation or code repair on its own.

V7 source-repair permission is internal application data, not a new client capability.
It binds the source/check hashes and current report; source repair preserves the entire
scenario list, including its order. Old frozen invocation contracts remain supported.
