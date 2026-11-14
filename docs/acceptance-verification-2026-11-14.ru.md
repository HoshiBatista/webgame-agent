# Сквозная приёмка, CI и локальный валидатор — 14.11.2026

Работа в `feature/game-analytics`, исходный коммит `ff38c78`. Проверки используют
только fixture/fake; реальных модельных вызовов, обновления облака и изменений
рабочей базы нет. PostgreSQL/Redis и учётная запись приёмки созданы отдельно.

## Исправления

`scripts/verify_container.py` больше не выполняет HTTP при импорте. Для правки
передаёт показанные `source_revision_id` и `source_artifact_hash`, сохраняет явный
fixture-профиль, проверяет ответы 409 для отсутствующего/устаревшего источника и
отсутствие лишнего Run после отказа. Проверяется весь набор исходников: меняется
только `styles.css`. Проверен hash экспорта после правки и настоящий формат SSE.
Параметры `--origin`, `--preview-origin`, `--output` позволяют использовать тот же
сценарий с Compose и нативным стендом. На успешном завершении свои чаты и публикация
удаляются; скрипт предназначен для отдельного тестового стенда.

В `.github/workflows/ci.yml`:

- `verify` запускает все контейнерные браузерные сценарии `tests` и `studio/tests`,
  кроме явно выделенных нативных и прямых тестов проигрывателя;
- `native-validator` на Ubuntu 22.04/24.04 сохраняет проверки OS sandbox и добавляет
  изолированные тесты проигрывателя Chromium/WebKit;
- отдельный `compose-acceptance` собирает и поднимает приложение, preview, worker,
  PostgreSQL 18, Redis и валидатор, затем выполняет настоящий HTTP-сценарий;
- Compose-проект имеет отдельное имя, fake/fixture, нулевой бюджет и тестовые
  реквизиты. JSON-отчёт сохраняется как artifact; при отказе выводятся логи стенда.
  Завершающий шаг удаляет только проект и volumes этого задания.

Общие задания закреплены на `ubuntu-24.04`, без плавающего `ubuntu-latest`.

`scripts/native.py prepare --local-linux-libs` загружает NSS/NSPR через настроенный
apt-репозиторий и распаковывает их в `.data/native-validator/linux-libraries`.
Нужны Debian/Ubuntu, `apt-get` и `dpkg-deb`; `sudo` и системная установка не нужны.
Это вариант для недостающих NSS/NSPR, а не замена всем зависимостям Playwright.
Каталог доступен sandbox только для чтения. Родительский loader path, DB URL,
токены и аудиоконфигурация в процесс проверки не наследуются.

Для Chromium выбран `--disable-audio-output`: он использует встроенный виртуальный
выходной поток, сохраняя обработку Web Audio и измеряемый сигнал. Конфигурация ALSA
сама по себе не устранила ошибку устройства в мобильном сценарии; она не стала
окончательным решением валидатора. Поведение флага подтверждается
[реализацией AudioManagerBase Chromium](https://chromium.googlesource.com/chromium/src/+/HEAD/media/audio/audio_manager_base.cc).
Наличие сигнала не означает проверку физических динамиков или приятности музыки.

Пять прежних тестов проигрывателя/preview больше не запускают браузер напрямую
на хосте. Они помечены `runtime_browser`; `scripts/verify_runtime_browser.py`
копирует только публичные исходники и запускает pytest внутри OS sandbox, без
модельных ключей, `.env`, `.git` и БД. JS работает в настоящих Chromium/WebKit.
Для локального Chromium предусмотрен явный `--engine chromium`.

Браузерные фикстуры запуска/ремонта обновлены под текущие обязательные `assets`
и сценарий клавиатуры. Дефекты синтаксиса, скрытый старт и неверные сценарии
остаются предметом тех же проверок; контракты генератора не ослаблены.
В регрессионных fixture-играх настольные сценарии reset/pause теперь используют
click вместо недопустимого на desktop действия tap. Проверки настоящих поломок
управления и паузы сохранены.

## Выполненные проверки

Среда: Ubuntu 24.04 / WSL2, Python 3.12.3 из отдельного dev-окружения,
PostgreSQL 18.7, Redis 7.0.15, Playwright 1.58.0, закреплённый Chromium 145.
Системная установка отсутствующих библиотек требовала пароль sudo; использованы
отдельные каталоги с публичными пакетами. Игровой код вне sandbox не запускался.

Полный backend без browser/native_browser/live: **1363 passed, 164 deselected**.
Ruff, mypy и синтаксическая проверка YAML прошли. Официальный Compose 2.39.4
выполнил `config --quiet` с синтетической конфигурацией, без чтения частного `.env`.

Подтверждены **157 разных браузерных сценариев**, включая studio workflows и проверки
изоляции. Это два дополняющих прогона: в первом 64 прошли, четыре desktop-сценария
выявили неверный тип ввода; после исправления пройдены все 99 сценариев от модуля
игровых регрессий до конца набора (пересечение — шесть уже прошедших случаев).
Список подтверждённых nodeid сохранён в машинном отчёте; исходные отказы не названы
успехом. Пять отдельных runtime-тестов прошли в настоящих **Chromium и WebKit**
внутри bubblewrap. Проверены сигнал Web Audio, mute, первая нота, сохранность
эффектов, клавиатура, смена ориентации и preview audio-control.

Для WebKit в Linux используется clocked `fakeaudiosink` GStreamer с приоритетом
`MAX`; plugins-bad входит в системные зависимости Playwright. На локальном стенде
публичные зависимости WebKit/GStreamer также распакованы без sudo; штатная
CI-установка использует `playwright install-deps chromium webkit`.

Сквозной HTTP-прогон использовал настоящие Gunicorn app/preview, Celery worker,
PostgreSQL, Redis и native Chromium. Проверены создание, источник правки, сохранность
механики, неизменность опубликованного снимка, ремикс, like, обновление публикации,
экспорт, SSE, CSRF, права и удаление. Все суммы расхода/резервов/unknown равны нулю.
После перезапуска процессов с итоговым кодом создание fixture заняло **3,211 с**,
правка **3,190 с** по HTTP; каждое задание использовало один вызов fake-провайдера.
Точные времена и ID сохранены в [машинном отчёте](evidence/acceptance-2026-11-14.json).
Время fixture не является измерением скорости настоящей модели.

## Повторение

Все команды выполняются из корня с настроенной отдельной тестовой PostgreSQL:

```sh
.venv/bin/python scripts/native.py prepare --local-linux-libs
.venv/bin/python scripts/native.py check
VALIDATOR_BACKEND=native .venv/bin/pytest tests studio/tests -m 'browser and not runtime_browser and not live' -k 'not real_unix_transport and not state_snapshot'
.venv/bin/python scripts/verify_runtime_browser.py --engine chromium
.venv/bin/pytest tests studio/tests -m 'not browser and not native_browser and not live'
.venv/bin/python scripts/verify_container.py --origin http://127.0.0.1:8000 --preview-origin http://localhost:8001
```

Для обоих движков проигрывателя установите системные зависимости Playwright
Chromium/WebKit и скачайте WebKit в тот же каталог:

```sh
.venv/bin/python -m playwright install-deps chromium webkit
PLAYWRIGHT_BROWSERS_PATH=.data/native-validator/browsers .venv/bin/python -m playwright install webkit
.venv/bin/python scripts/verify_runtime_browser.py
```

## Границы

Два теста с прямым `docker exec` выполняются в контейнерном CI. Docker Engine в этой
WSL-интеграции недоступен, поэтому локальный HTTP-прогон не объявляется проверкой
Docker-образов или nginx. Добавление workflow и проверка Compose-конфигурации сами
по себе не подтверждают зелёный удалённый CI. Настоящая модель, физический телефон
и целевой WebView остаются отдельными видами проверки.

После push GitHub принял workflow, но [запуск 43572727043](https://github.com/HoshiBatista/webgame-agent/actions/runs/43572727043)
завершился до выполнения шагов: все четыре задания получили сообщение о блокировке
учётной записи из-за проблемы биллинга. Ни один тест удалённо не запускался.
Разблокировка биллинга относится к владельцу аккаунта; настройки оплаты не менялись.
