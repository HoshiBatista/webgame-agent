# GameForge — быстрые мини-игры

Короткий запрос → HTML5-мини-игра → проверка настоящим браузером → игра в телефоне,
точечные правки, история, публикация и ремикс. Механики генерирует модель; каталог готовых
игр не подменяет генерацию. Ветка `mini-games` отслеживает `origin/mini-games`.

Реализованы Django/DRF, PostgreSQL 18, Celery/Redis, React/TypeScript/SCSS, локальный
Codex-login и сменный API-адаптер vLLM. Нормальный путь — один запрос модели и проверка,
при проблеме — одна автоправка. Исходники и отчёты сохраняются, бесконечных исследований нет.
Полный статус и ограничения: [план](docs/development-plan.md), [проверки](docs/verification.md).
Реальный vLLM пока недоступен: проверен его протокол, не качество локальной модели.

В том же ответе модель рассчитывает размеры полезного игрового поля, объектов и
управления для телефона и ПК. Увеличение одного Canvas или фона не считается выполнением
этого требования. Правила конкретной игры определяют, какие пропорции можно менять;
единого шаблона поля нет. Проверки механик не подменяют визуальную оценку результата.

## Локально с входом через Codex

Нужны Python 3.12+, Node 22+, PostgreSQL 18+, Redis 7, Docker и установленный Codex CLI
с выполненным входом. Сейчас профиль без инструментов проверен для
`codex-cli 0.163.0-alpha.10.2`; при другой версии генерация отказывает до платного запроса.
Не копируйте авторизацию Codex в проект, образы или CI.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
npm ci --prefix web
npm run build --prefix web
cp .env.example .env
```

В `.env` задайте случайный `DJANGO_SECRET_KEY`, имя и длинный пароль начального
администратора, подключения к своей БД/Redis. Файл исключён из Git. Для установленного
локального PostgreSQL используется `DATABASE_URL=postgresql:///gameforge_mini`;
пустую БД можно создать через `createdb gameforge_mini`. Администратор создаётся после
миграций; повторный запуск не меняет его пароль. Других демо-пользователей создаёт оператор
через Django admin/management shell, публичной регистрации нет.

Если Redis для этого проекта ещё не запущен:

```sh
docker run -d --name gf-mini-redis -p 127.0.0.1:56379:6379 redis:7-alpine redis-server --appendonly yes
```

Запуск собственной изолированной проверки и приложения:

```sh
sh scripts/validator-start.sh
.venv/bin/python scripts/dev.py start
.venv/bin/python scripts/dev.py status
```

Открыть **http://127.0.0.1:8000/**. Игровой origin — **http://localhost:8001/**;
на его корне 404 ожидаем, сама игра доступна по подписанной ссылке. Используйте именно
127.0.0.1 для приложения, чтобы host-only cookie не уходила на игровой localhost.
`status` проверяет процессы; фактическая доступность API — `/api/health/`.
Логи и PID-файл находятся в `.data/`. Остановка: `.venv/bin/python scripts/dev.py stop`.
Скрипт управляет только записанными им процессами с совпадающими PID, временем старта и аргументами.

По умолчанию используется доступная в каталоге Codex модель `gpt-6-luna`, effort low.
В интерфейсе можно выбрать другую модель с настроенным тарифом. Общий тестовый бюджет
этой установки — **$50**. Это API-эквивалент расхода подписки, не списание с карты.
Изменение `.env` не обнуляет существующий журнал или лимит в БД. Контекст текущей
мини-игры ограничен 256000 байтами UTF-8 вместе со схемой; превышение отклоняется до
отправки, код не обрезается. Лимит устраняет скрытую compaction в данном коротком профиле.

Неизвестный расход после обрыва остаётся отдельной ответственностью, а не вечным
активным резервом. Оператор сверяет независимые данные провайдера и только затем
использует `manage.py reconcile_invocation --help`. Эта команда не делает новых вызовов
и не должна применяться с выдуманным нулевым usage.

## Контейнерная поставка и будущий vLLM

```sh
docker compose up --build -d
```

Приложение: http://127.0.0.1:8080/, preview: http://localhost:8081/.
Compose по умолчанию использует явно помеченный `fake` для проверки установки;
это **не настоящая генерация**. Codex-login запускается только локальным оператором,
в образы не переносится. Собственные PostgreSQL/Redis имеют именованные volumes.
Проверяющий контейнер работает без сети, с read-only файловой системой и без секретов;
worker обращается к нему через отдельный Unix-сокет, без Docker socket.

Для будущего API установите `CONTAINER_PROVIDER=vllm`, `CONTAINER_MODEL` или
`GAMEFORGE_VLLM_MODEL`, `GAMEFORGE_VLLM_URL`, при необходимости ключ,
`GAMEFORGE_VLLM_JSON_MODE` и `GAMEFORGE_VLLM_STREAM`. В `GAMEFORGE_PRICES_JSON` задайте
подтверждённые для модели `context_window`, `max_output_tokens` и цены; у собственной
модели допустим явный нулевой денежный тариф. Usage всё равно сохраняется. Ключ получает
только worker. Подробности и ограничения: [generation/README.md](generation/README.md).
Домен `digsy.ru`, TLS и конкурсный WebView требуют отдельной среды; сейчас стенд локальный.

## Проверки и измерения

```sh
.venv/bin/ruff check gameforge studio generation validation scripts tests
.venv/bin/mypy generation validation --ignore-missing-imports
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/pytest -m 'not browser and not live'
VALIDATOR_CONTAINER=gf-mini-validator-tests sh scripts/validator-start.sh
VALIDATOR_CONTAINER=gf-mini-validator-tests .venv/bin/pytest tests/test_validation.py -m browser
npm run lint --prefix web
npm test --prefix web
npm run build --prefix web
```

Браузерные тесты используют отдельный `gf-mini-validator-tests`, чтобы не конкурировать
с текущей генерацией за память одного браузерного контейнера; backend-тесты — PostgreSQL с правом
создать тестовую БД. CI выполняет эти проверки, сборку контейнеров и не делает платных вызовов.
Ручной платный пилот запускается только при выделенном бюджете:

```sh
.venv/bin/python scripts/live_eval.py --output .data/pilot.json --prefix my-unique-pilot
```

Скрипт сохраняет ID каждой операции до ожидания, продолжает наблюдение после перезапуска,
не повторяет ошибку скрыто и не засчитывает ручное подтверждение как автоматический успех.
Пять разных запросов и две правки на успешную игру — пилот, недостаточный для устойчивого p95.
Цели создания p50≤30с/p95≤60с, правки p50≤10с/p95≤20с — внутренние ориентиры, а не таймеры
обрыва модели. Фактические результаты публикуются с ошибками и всеми повторными вызовами.

## Документы

- [Текущая модель создания игры](docs/game-creation-model.ru.md), [архитектура](docs/architecture.md).
- [Требования с источниками](docs/requirements.ru.md), [API](docs/api.md).
- [План и статус](docs/development-plan.md), [отчёт испытаний](docs/verification.md).
- [Демонстрация на 3–5 минут](docs/demo.ru.md), [контейнерная проверка](docs/container-verification.md).
- [Проверка интерфейса F01–F15](docs/frontend-verification.md), [локальная проверка WKWebView](docs/wkwebview-smoke.md).
- [Разбор ветки ML-инженера](docs/source-review.ru.md), [исходные материалы](docs/sources/README.md).

Расширенный GamesForgeEx развивается отдельно в `/Users/noxlight7/study/GamesForgeEx`.
Новый проект не импортирует его код и не поддерживает прежние игры. Архив старой установки
находится вне репозитория; это резервная копия, не путь исполнения. Git-история сохранена,
другие ветки не переписывались.
