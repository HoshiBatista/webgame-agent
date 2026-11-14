# GameForge — генератор мини-игр

GameForge создаёт браузерные мини-игры по текстовому описанию. Опишите идею,
выберите модель и аудиторию, затем играйте, просите изменения и сохраняйте
понравившиеся версии. Готовой игрой можно поделиться по ссылке или скачать её HTML.

## Возможности

- Создание и доработка игры в чате с предпросмотром.
- История версий и возврат к сохранённому варианту.
- Автоматическая проверка кода, управления и игровых сценариев в отдельном браузере.
- Повторная проверка выбранной версии без новой генерации.
- Публикация игр, общая лента, отзывы и оценки.
- Личные шаблоны запросов и пожелания для следующих игр.
- Необязательные идеи для новой игры на основе подписанных демоданных.
- Светлая, тёмная и системная темы; интерфейс для компьютера и телефона.

## Режимы генерации

Модель выбирается в шапке чата или в настройках аккаунта. Можно начать с Lite,
а продолжить доработку с Pro. Уже запущенное задание сохраняет выбранную для него модель.
Pro подключается через Codex Worker или локальный Codex CLI; Lite — через relay/vLLM.
Доступность моделей зависит от конфигурации установки.

## Устройство проекта

Серверная часть использует **Django / Django REST Framework**, **PostgreSQL**
и **Celery / Redis**. Интерфейс написан на **React / TypeScript / SCSS**.
Сгенерированный HTML/CSS/JavaScript выполняется на отдельном origin в изолированном
браузере, без доступа к базе данных и секретам приложения.

| Каталог | Назначение |
| --- | --- |
| `gameforge/` | Настройки и конфигурация Django |
| `studio/` | Чаты, версии, публикации и фоновые задания |
| `generation/` | Подключение моделей, инструкции генерации и применение правок |
| `validation/` | Браузерная проверка игр |
| `web/` | Веб-интерфейс |
| `deploy/` | Конфигурация развёртывания |
| `scripts/` | Запуск, обслуживание и проверки |
| `docs/` | Документация |

## Запуск через Docker Compose

Нужны Docker с Compose, свободные порты **8080/8081** и доступ к провайдеру модели.
Командный шаблон настроен на relay; персональный client-токен выдаёт администратор.

```sh
git clone --branch main https://github.com/HoshiBatista/webgame-agent.git GameForge
cd GameForge
```

Создайте локальный `.env`, сохранив существующий, если он уже есть:

```sh
if [ ! -e .env ]; then
  (umask 077; cp .env.team.example .env)
fi
```

Заполните значения в `.env`:

| Переменная | Значение |
| --- | --- |
| `DJANGO_SECRET_KEY` | Случайный секрет приложения |
| `DJANGO_SUPERUSER_USERNAME` | Логин первого администратора |
| `DJANGO_SUPERUSER_PASSWORD` | Пароль администратора, минимум 10 символов |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL из шестнадцатеричных символов |
| `GAMEFORGE_RELAY_URL` | Адрес реле без `/v1` |
| `GAMEFORGE_RELAY_API_KEY` | Персональный client-токен реле |

Для relay оставьте `CONTAINER_PROVIDER=relay` и укажите модель в `CONTAINER_MODEL`.
Секреты храните только в локальной конфигурации; `.env` не добавляйте в Git.

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
curl --fail --show-error http://127.0.0.1:8080/api/health/
```

Откройте **http://127.0.0.1:8080/** и войдите с данными администратора из `.env`.
Сервис `init` применяет миграции и создаёт первоначальную учётную запись;
его завершение со статусом `Exited (0)` ожидаемо.

Предпросмотр использует **http://localhost:8081/**. Игры открываются по ссылкам
из приложения; ответ 404 на корне этого адреса ожидаем. Разные адреса отделяют
игровые страницы от cookie приложения.

Без настройки провайдера Compose использует `fake` для проверки инфраструктуры.
Для настоящей генерации необходимо подключение модели.
Подробнее: [установка для команды](docs/team-local-setup.ru.md).

## Запуск без Docker

Поддерживаются macOS, Linux и WSL2. Нужны **Python 3.12**, **Node.js 22+**,
**PostgreSQL 18+** и **Redis 7+**. Подготовьте базу, Redis и приватный `.env`
по [инструкции нативной установки](docs/native-local-setup.ru.md), используя
[шаблон](.env.native.example).

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip check
npm ci --prefix web
npm run build --prefix web
.venv/bin/python scripts/native.py prepare
TZ=UTC .venv/bin/python scripts/dev.py start
```

Для этого способа установите `VALIDATOR_BACKEND=native`. Подготовка скачивает Chromium
и проверяет изоляцию средствами ОС: `sandbox-exec` на macOS, `bubblewrap` на Linux/WSL2.
Приложение доступно на **http://127.0.0.1:8000/**, предпросмотр — на **http://localhost:8001/**.
PostgreSQL и Redis запускаются отдельно.

## Обновление и остановка

Перед обновлением дождитесь завершения активных заданий и сделайте резервную копию базы.
Сохраните `.env` и собственные изменения. После получения новой версии для Compose:

```sh
git pull --ff-only
docker compose stop
docker compose build
docker compose run --rm init
docker compose up -d
```

Для обычной остановки достаточно `docker compose stop`. Данные хранятся в volumes;
не удаляйте их, если нужна история игр.

В нативной установке управляйте процессами через `scripts/dev.py`:

```sh
TZ=UTC .venv/bin/python scripts/dev.py stop
TZ=UTC .venv/bin/python scripts/dev.py status
TZ=UTC .venv/bin/python scripts/dev.py start
```

После обновления исходников повторите установку зависимостей, сборку интерфейса
и подготовку валидатора. Приложение и валидатор должны использовать одну версию кода.

## Проверки для разработки

Серверным тестам нужна настроенная PostgreSQL с правом создания тестовой базы.

```sh
.venv/bin/ruff check gameforge studio generation validation scripts tests
.venv/bin/mypy generation validation --ignore-missing-imports
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/pytest -m 'not browser and not native_browser and not live'
npm run lint --prefix web
npm test --prefix web
npm run build --prefix web
```

Браузерные проверки с отдельным контейнером валидатора:

```sh
VALIDATOR_CONTAINER=gf-mini-validator-tests sh scripts/validator-start.sh
VALIDATOR_CONTAINER=gf-mini-validator-tests .venv/bin/pytest tests studio/tests -m 'browser and not native_browser and not runtime_browser and not live'
```

Нативный изолированный валидатор (macOS/Linux/WSL2):

```sh
.venv/bin/python scripts/native.py prepare
VALIDATOR_BACKEND=native .venv/bin/pytest tests studio/tests -m 'browser and not runtime_browser and not live' -k 'not real_unix_transport and not state_snapshot'
.venv/bin/python scripts/verify_runtime_browser.py --engine chromium
```

Два исключённых теста используют `docker exec` напрямую и выполняются в контейнерном CI.
Тесты общего проигрывателя (`runtime_browser`) запускаются отдельным скриптом внутри
sandbox, с публичными исходниками и без доступа к БД/`.env`. Для обоих движков
подготовьте WebKit и его зависимости через Playwright, используя тот же
`PLAYWRIGHT_BROWSERS_PATH=.data/native-validator/browsers`, затем запустите скрипт без
`--engine chromium`. CI выполняет оба движка.
Если на Debian/Ubuntu отсутствуют только NSS/NSPR и нет `sudo`, подготовьте публичные
библиотеки локально: `.venv/bin/python scripts/native.py prepare --local-linux-libs`.
Они доступны браузеру только для чтения; ограничения ОС и сети сохраняются.

Сквозная HTTP-проверка на отдельном стенде с `CONTAINER_PROVIDER=fake` и
`CONTAINER_MODEL=fixture`, запущенными worker и валидатором:

```sh
.venv/bin/python scripts/verify_container.py
# Для нативного стенда:
.venv/bin/python scripts/verify_container.py --origin http://127.0.0.1:8000 --preview-origin http://localhost:8001
```

Нужны тестовые `DJANGO_SUPERUSER_USERNAME`/`DJANGO_SUPERUSER_PASSWORD`. Скрипт создаёт
тестовые чаты, проверяет создание, точечную правку, публикацию, ремикс и экспорт,
затем удаляет свои чаты/публикацию. На другом провайдере отказывается создавать Run.
Отчёт: `.data/container-verification.json`. CI выполняет его в отдельном Compose-проекте
и удаляет только volumes этого проекта.

## Демонстрационная аналитика

Функция по умолчанию выключена. После применения миграций загрузите встроенный
вымышленный набор; команда не обращается к модели:

```sh
# Docker Compose
docker compose exec app python manage.py load_demo_analytics
# Либо нативная установка
.venv/bin/python manage.py migrate
.venv/bin/python manage.py load_demo_analytics
```

Установите `GAMEFORGE_ANALYTICS_ENABLED=1` в приватном `.env` и перезапустите
приложение и worker (`docker compose up -d` либо stop/start через `scripts/dev.py`).
В новом чате откройте «Что подсказывают данные» и выберите до двух идей. Они относятся
к одной новой игре; общие пожелания аккаунта не меняются. Изменение аудитории очищает
выбор. В истории сохраняются основание и состояние передачи модели.

Это демонстрация контура рекомендаций, без сбора реальных действий игроков.
[Реализация, проверки и ограничения](docs/game-analytics-implementation.ru.md).

## Документация

- [Проектирование полного кабинета аналитики: шесть направлений, сбор и этапы](docs/product-analytics-design.ru.md) — запланировано, ещё не реализовано.

- [Сквозная приёмка, CI и нативный валидатор — 14.11](docs/acceptance-verification-2026-11-14.ru.md).
- [Контракт аналитики игр и рекомендаций](docs/game-analytics-design.ru.md).
- [Проверка чистой установки и исправления тестовых фикстур](docs/clean-install-verification-2026-11-13.ru.md).
- [Локальный запуск с Docker](docs/team-local-setup.ru.md) и [без Docker](docs/native-local-setup.ru.md).
- [Облачное развёртывание](docs/cloud-deployment.ru.md).
- [Архитектура](docs/architecture.md) и [процесс создания игры](docs/game-creation-model.ru.md).
- [API](docs/api.md) и [устройство генератора](generation/README.md).
- [Подключение реле](docs/relay-deployment.md) и [диагностика LLM](docs/llm-diagnostics.md).
- [Проверка игровых версий](docs/validation-v4-implementation.ru.md).

## Метрики, трейсы и технические события

Опциональный контур Prometheus/Grafana + Tempo/Loki/Collector/Alertmanager содержит
готовые панели, правила оповещений и отдельный сборщик ledger/PG/Redis. Промпты,
игровой код, ответы модели и секреты в телеметрию не поступают.

```sh
python scripts/prepare_observability.py
docker compose -f compose.yaml -f deploy/observability.compose.yaml up -d --build --wait --wait-timeout 180
.venv/bin/python scripts/verify_observability.py --ready-only --timeout 180
```

Grafana: http://127.0.0.1:3000, пользователь `admin`, пароль — в приватном файле
`.data/observability-secrets/grafana_admin_password`. [Запуск, метрики, ограничения,
проверки и диагностика](docs/observability.ru.md). Контур требует дополнительных ресурсов;
облако автоматически не обновляется.
