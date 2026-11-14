# Наблюдаемость GameForge

Контур включается отдельно: **Prometheus 3.16.0, Grafana OSS 13.3.1, Tempo 2.10.10,
Loki 3.7.10, OpenTelemetry Collector 0.165.0 и Alertmanager 0.35.0**.
Версии и multi-architecture image digests закреплены; Python SDK/экспортёры OpenTelemetry — 1.45.2 в обоих lock-файлах.
Это конфигурация одного сервера с локальными томами, без высокой доступности.

## Запуск

Сначала выполните обычную настройку `.env` из README. Все команды — из корня проекта.
Для работающей установки достаточно собрать новый app image: миграцию добавления
контекста трассировки выполнит штатный `init`.

```sh
python scripts/prepare_observability.py
docker compose -f compose.yaml -f deploy/observability.compose.yaml config --quiet
docker compose -f compose.yaml -f deploy/observability.compose.yaml up -d --build --wait --wait-timeout 180
.venv/bin/python scripts/verify_observability.py --ready-only --timeout 180
```

Grafana: **http://127.0.0.1:3000**, логин `admin`. Пароль находится в
`.data/observability-secrets/grafana_admin_password`. Откройте этот файл локально;
не отправляйте его в Git, чат, отчёты или аргументы команд.
Для другого порта задайте `GRAFANA_PORT` и передайте его проверяющему скрипту
через `--grafana-url`.

Подготовка секретов идемпотентна: существующие значения сохраняются. Каталог имеет
права 0700, файлы 0600. Compose secrets в локальном Docker используют bind mounts
и не гарантируют смену владельца файла. Поэтому одноразовый контейнер без сети
копирует их в отдельный том с правами 0400 для UID приложения/пользователя Grafana.
Он также подготавливает владельца томов Tempo и Loki; остальные сервисы непривилегированные.

Для облачной **установки оператором** порядок файлов такой:

```sh
docker compose --env-file .env -f compose.yaml -f deploy/cloud.compose.yaml -f deploy/observability.compose.yaml config --quiet
```

В этой работе облако не обновляется. Для доступа к Grafana на удалённом сервере
используйте SSH-туннель на его loopback-порт. Не публикуйте наружу OTLP, Loki, Tempo,
Prometheus и Alertmanager: их внутренние API не имеют пользовательской авторизации.
Дополнительные ресурсы следует проверить до включения на существующем VPS.

## Данные и границы измерений

| Область | Что собирается |
| --- | --- |
| HTTP / preview | Число запросов, метод, код ответа, шаблон маршрута, гистограмма времени до готовности объекта ответа |
| Run | Создание, завершение по статусам, отмена, очередь, полное время, сумма времени модели, проверок и упаковки |
| Модели | Первые durable sent-маркеры игровых Invocation, финальные токены, состояния квитанций, длительности transport по операциям и исходам |
| Celery | Время от публикации до начала задачи, выполнение, исход, heartbeat worker и публикация тиков beat |
| Валидатор | Длительность обращения к изолированному браузеру, исход, ограниченные коды findings, состояния автоматических/ручных проверок |
| Отзывы | Состояния отдельной фоновой обработки, связанный span обращения к провайдеру |
| Бюджет | Лимит, известный расход, резервы, неизвестный расход и доступный остаток из существующего ledger |
| PostgreSQL | Соединения клиентов по состоянию, предел соединений, размер БД, commits/rollbacks, deadlocks, cache/disk reads |
| Redis | Длина стандартных четырёх приоритетных очередей Celery, память/лимит, клиенты, evictions, hits/misses и команды |
| Процессы | CPU, RSS и открытые FD на Linux, uptime, свежесть экспорта, роль и версия сервиса |
| Телеметрия | Доступность хранилищ, очереди/ошибки экспортёров, отказы memory limiter, размер блоков Prometheus |

Суффиксы Prometheus: счётчики `_total`, гистограммы `_bucket`, `_sum`, `_count`.
Например, `gameforge_http_requests_total`, `gameforge_run_seconds_bucket`,
`gameforge_budget_unknown_usd`, `gameforge_dependency_up`.

Время HTTP заканчивается при возвращении Django response. Оно **не измеряет** весь
SSE-поток или скачивание. `/api/health/`, `/health/` preview и `/assets/` исключены.
Длительность provider transport включает получение receipt/ожидание и нормализацию;
её количество не равно количеству новых платных отправок. Повторное чтение receipt
не увеличивает `invocations_sent_total`. Токены отмечаются только для финального
не-unknown ответа; `input` уже включает `cached_input`.

События/счётчики работают best effort: аварийное завершение процесса или переполнение
очереди могут потерять наблюдения. Они не заменяют бухгалтерию. Сборщик `observe-state`
каждые 30 секунд читает согласованный snapshot PostgreSQL, включая обработку отзывов;
при пустой БД не создаёт Budget. `spent`, `reserved` и `unknown` не смешиваются.
Нулевой бюджет fake-проверки не вызывает `BudgetLow`. Цены повторно не рассчитываются.

Gauge состояния — текущие/сохранённые количества, не monotonic counters: удаление
данных или смена статуса может уменьшить их. Для них не применяют `rate()`.
Статистические счётчики Redis/PostgreSQL могут сброситься после перезапуска/reset stats.
При рестарте процесса Collector хранит его последний набор series до 90 секунд;
панели одиночного durable snapshot используют `max`, не складывают дубликаты.
Следите за `state_snapshot_timestamp_seconds` и `state_collection_success`:
недоступная БД не превращается в ложные нули бюджета.

Успех задачи Celery означает завершение обработчика; Run при этом может остаться
`needs_attention`/`unverified`. Только существующая политика приложения определяет
приёмку игры. `fake` виден отдельным provider; эти данные не доказывают задержки и
качество настоящих моделей. Gates/аудиосигнал не доказывают красоту, FPS или приятность музыки.

## Трейсы и события

Ручные spans: HTTP → Celery → `gameforge.run_process` → `provider_transport` →
`validation_job` → `validator`. Контекст `traceparent` сохраняется отдельно в Run,
ValidationTask и FeedbackProcessing: восстановление из outbox/после рестарта может
продолжить исходный trace. В запрос модели, source/hash и игровые артефакты он не попадает.
Входящие заголовки trace/baggage публичного браузера не принимаются. Thread/prefork
worker получает отдельное состояние SDK для каждого процесса.

В Loki поступают только явно разрешённые структурированные operational events,
например `run.finished` и `invocation.resolved`. JSON содержит `trace_id`; Grafana
связывает его с Tempo, а из Tempo можно открыть события того же trace. Полные stdout,
Django/Gunicorn/Celery-логи и транспортные ответы автоматически **не собираются**.
Для диагностики таких журналов сохраняется существующий приватный порядок доступа.

Не экспортируются: промпты, исходники игр, ответы моделей, свободный текст ошибок,
SQL, аргументы/результаты задач, пожелания, имена/ID пользователей, API-ключи, cookies,
headers, raw URL/query string, preview token. UUID заданий разрешены только в приватных
traces/events, не в метриках. Labels провайдера/профиля/операции/исхода имеют фиксированные
наборы; маршрут — разрешённый Django pattern.

SDK не подключается к глобальным логгерам/автоматическому HTTP/SQL-инструментированию.
Ресурсы задаются явно; общий `OTEL_RESOURCE_ATTRIBUTES` не подмешивается. Экспортирующая
HTTP-сессия не использует netrc/proxy из окружения, отбрасывает дополнительные SDK
headers и не следует редиректам. Приватные данные приложения не передаются в валидатор.
Контейнер валидатора по-прежнему без сети и без секретов; spans создаёт контроллер.

`observability_role` создаёт `gameforge_metrics` с `pg_monitor`, лимитом 3 соединения,
read-only по умолчанию и statement timeout 5 секунд. SELECT разрешён только на явно
перечисленные технические колонки шести таблиц. Существующие расширенные привилегии,
владение объектами и посторонние наследуемые роли приводят к отказу конфигурации.
Роль/её пароль остаются служебными: `pg_monitor` сам по себе имеет доступ к статистике
PostgreSQL, поэтому отдавать эти реквизиты пользователям нельзя.

## Панели и оповещения

В папке **GameForge** автоматически появляются четыре dashboards:

- **Overview**: здоровье, свежесть ledger, статусы Run, отдельные корзины бюджета и alerts.
- **HTTP**: частота, статусы, p50/p95/p99 и медленные шаблоны маршрутов.
- **Generation & queue**: исходы, transport, токены, worker, проверки, отзывы и outbox.
- **Infrastructure**: процессы, PostgreSQL, Redis, heartbeat и сама телеметрия.

Правила находятся в `deploy/observability/rules.yaml`: Collector/storage down,
устаревший observer, недоступные зависимости, отсутствие worker/beat, долгое ожидание,
просроченные leases, неизвестный расход, низкий бюджет, HTTP 5xx/latency, соединения PG,
память/evictions Redis, отказы/ошибки Collector и приближение TSDB к лимиту.
Начальные пороги требуют настройки по реальному трафику. Длительная игра сама по себе
не считается отказом модели. Подозрение на неизвестный расход не запускает повторную генерацию.

Alertmanager по умолчанию имеет **local-only** receiver: alerts видны через datasource
в Grafana, уведомления людям не отправляются. Для почты/мессенджера оператор отдельно
настраивает receiver и его secrets. Не записывайте токены в этот конфиг.

## Ресурсы и хранение

Metrics: 14 дней и не более 5 GB блоков TSDB (WAL/head дополнительно).
Traces: 72 часа. Events: 7 дней. Удаление по сроку у Tempo/Loki выполняется фоново;
это не жёсткая дисковая квота. Используются отдельные именованные тома.
Общий предел памяти дополнительных сервисов — около 3 GiB; это верхние ограничения,
не измеренная ёмкость сервера. Планируйте порядка 6 GiB RAM для полного стенда с приложением
и браузером, дисковый запас и внешний контроль свободного места хоста.
Privileged cAdvisor/node exporter и Docker socket не добавлены. Локальные диски —
одна точка отказа; для production HA/резервирования нужен отдельный проект.

Переменные: `GAMEFORGE_ENVIRONMENT=local`, `GAMEFORGE_RELEASE=dev`,
`GAMEFORGE_TRACE_SAMPLE_RATIO=1`, `GRAFANA_PORT=3000`. Environment/release — короткие
несекретные идентификаторы; release удобно задавать Git SHA. Ratio допускает 0..1;
при уменьшении доли spans часть traces/events и exemplars не будет иметь полного trace.
Метрики и финансовый ledger не семплируются. Стандартный экспорт SDK — раз в 10 секунд.

Чтобы выключить контур, установите `GAMEFORGE_OBSERVABILITY_ENABLED=0` у приложения,
worker, beat и preview и пересоздайте их без overlay. Дополнительные сервисы можно
остановить явно; не используйте `down --volumes` на рабочей установке — base Compose
содержит также том PostgreSQL. Подготовленные панели восстанавливаются из Git;
пароли/настройки Grafana и telemetry volumes резервируются отдельно.
Для смены Grafana admin-пароля используйте Grafana: переменная initial admin password
не меняет существующего пользователя. После ротации DB secret заново выполните
`telemetry-storage-init`, `observability-init` и пересоздайте `observe-state`.

## Проверка

Сначала запустите readiness выше. На **отдельном disposable стенде с fake provider**:

```sh
.venv/bin/python scripts/verify_container.py --output .data/container-verification.json
.venv/bin/python scripts/verify_observability.py --output .data/observability-verification.json
```

Первый скрипт создаёт/меняет/публикует/ремиксит/экспортирует тестовую игру штатными HTTP
запросами. Второй не вызывает модель: через авторизованный Grafana proxy проверяет
метрики, пять зависимостей, полный Run/provider/browser trace и связанное событие Loki.
В `.github/workflows/ci.yml` этот сценарий включён в Compose acceptance,
включая повторную HTTP-приёмку при остановленном Collector.

Проверка конфигов и правил на доступном Docker Engine:

```sh
docker compose -f compose.yaml -f deploy/observability.compose.yaml run --rm --no-deps --entrypoint /bin/promtool prometheus check config /etc/prometheus/prometheus.yaml
docker compose -f compose.yaml -f deploy/observability.compose.yaml run --rm --no-deps --entrypoint /bin/promtool -v "$PWD/deploy/observability:/rules:ro" -w /rules prometheus test rules rules.test.yaml
docker compose -f compose.yaml -f deploy/observability.compose.yaml run --rm --no-deps otel-collector validate --config=/etc/otelcol/config.yaml
docker compose -f compose.yaml -f deploy/observability.compose.yaml run --rm --no-deps loki -config.file=/etc/loki/config.yaml -verify-config
.venv/bin/pytest tests/test_observability.py studio/tests/test_observability.py tests/test_packaging.py
```

## Диагностика

Сначала посмотрите свежесть observer, `dependency_up`, worker/beat heartbeat и targets.
`StateObserverStale`: проверьте `observe-state` и права роли после миграций.
`TelemetryCollectorDown`/export failures: конфиг, память, DNS и доступность Tempo/Loki;
падение экспорта не должно менять исход Run или повторять модельный вызов.
`RunQueueStalled`: worker, beat, outbox, лимит провайдера и бюджет; не очищайте квитанции.
`UnknownModelSpend`: сначала получите существующий receipt по штатной политике.
При ограничении диска уменьшите retention/нагрузку и сохраните нужные диагностические данные.
Не устраняйте alerts удалением игровых данных или финансового учёта.

Источники конфигурации: [Loki OTLP](https://grafana.com/docs/loki/latest/send-data/otel/),
[Tempo local storage](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/deploy/locally/linux/),
[Collector Prometheus exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/exporter/prometheusexporter),
[правила Prometheus](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).
