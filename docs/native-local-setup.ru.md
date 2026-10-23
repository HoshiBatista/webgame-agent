# GameForge без Docker: macOS, Linux и WSL2

Код берём из ветки `mini-games`; администратор отдельно передаёт персональный
`participant-N.env` с client-токеном реле. VPN и SSH участнику не нужны.
GameForge, PostgreSQL, Redis и браузер проверки работают локально без Docker.
GPU, модель и облачное реле уже обслуживаются оператором.

## 1. Установите системные зависимости

Нужны Python **3.12**, Node **22+**, PostgreSQL **18+**, Redis **7+** и Git.
Команды ниже рассчитаны на новую установку. Если PostgreSQL или Redis уже работают,
используйте согласованные адреса/роли, не останавливайте чужие службы ради порта.

### macOS

С установленным [Homebrew](https://brew.sh/):

```sh
brew install python@3.12 node@22 postgresql@18 redis
export PATH="$(brew --prefix python@3.12)/bin:$(brew --prefix node@22)/bin:$(brew --prefix postgresql@18)/bin:$PATH"
brew services start postgresql@18
brew services start redis
createdb gameforge_mini
```

`createdb` выполняется один раз: сообщение о существующей базе не означает необходимость
её удалять. Строку `export PATH=…` добавьте в свой профиль shell или повторяйте в новых
терминалах. Браузер защищается встроенным `/usr/bin/sandbox-exec`; дополнительная VM не нужна.

### Linux / WSL2

В WSL2 используйте Linux-дистрибутив, храните проект в `~/…`, а не `/mnt/c/…`.
Нативный Windows/PowerShell и WSL1 этим способом не поддерживаются.

Пример для Ubuntu 24.04 с Python 3.12:

```sh
sudo apt update
sudo apt install python3.12 python3.12-venv redis-server bubblewrap git
```

Node 22+ установите доступным в команде способом; системный пакет старой Ubuntu может
быть слишком старым. Для PostgreSQL нужен именно 18+: стандартный `apt install postgresql`
на Ubuntu 24.04 может установить другую версию. Подключите
[официальный репозиторий PostgreSQL](https://www.postgresql.org/download/linux/ubuntu/), затем:

```sh
sudo apt install postgresql-18 postgresql-client-18
sudo systemctl start postgresql redis-server
sudo -u postgres createuser --login "$(id -un)"
sudo -u postgres createdb --owner="$(id -un)" gameforge_mini
```

Последние две команды нужны только для новой роли/БД. Они создают роль без superuser;
локальный вход использует peer-аутентификацию. При уже существующей роли используйте её.
В WSL без systemd запуск служб: `sudo service postgresql start` и
`sudo service redis-server start`. На другом дистрибутиве установите эквивалентные пакеты.

Для `bubblewrap` ОС должна разрешать пользовательские namespace. Проверка ниже обнаружит
запрет ядра/AppArmor. Не отключайте общесистемные механизмы защиты ради запуска: согласуйте
профиль `bwrap` с администратором или используйте контейнерный вариант из README.

Для обеих ОС проверьте версии и службы:

```sh
python3.12 --version
node --version
psql -d gameforge_mini -Atc 'show server_version'
redis-cli ping
```

Redis должен ответить `PONG`. Он и PostgreSQL предназначены для локального доступа;
открывать их порты в интернет не требуется.

## 2. Получите код и зависимости

```sh
git clone --branch mini-games https://github.com/HoshiBatista/webgame-agent.git GameForge
cd GameForge
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
npm ci --prefix web
npm run build --prefix web
```

На Linux/WSL2 дополнительно установите системные библиотеки Chromium:

```sh
.venv/bin/python -m playwright install-deps chromium
```

Команда может запросить sudo для пакетного менеджера. На macOS этот шаг не нужен.
Затем **на обеих ОС**:

```sh
.venv/bin/python scripts/native.py prepare
```

Команда скачает Chromium версии из закреплённого Playwright в
`.data/native-validator/browsers`, запустит пустой браузер в изоляции и проверит версию.
Ожидаемый результат — `Native OS sandbox and Chromium: OK`. Модель не вызывается.
Проект не использует личный Chrome-профиль или сохранённые в нём пароли.
Принцип установки браузера описан в [документации Playwright](https://playwright.dev/python/docs/browsers).

## 3. Создайте свою конфигурацию

```sh
(
  set -e
  umask 077
  if [ -e .env ]; then
    echo '.env уже существует: измените нужные строки, не перезаписывайте файл.'
    exit 1
  fi
  cp .env.native.example .env
)
```

Откройте `.env` редактором, замените все `CHANGE_ME`:

- `DJANGO_SECRET_KEY` — случайная строка, например результат `openssl rand -hex 32`;
- `DJANGO_SUPERUSER_PASSWORD` — свой пароль входа, минимум 10 символов;
- `GAMEFORGE_RELAY_API_KEY` — значение из вашего персонального файла доступа.

Сохраните `GAMEFORGE_PROVIDER=relay`, `GAMEFORGE_MODEL=qwen38` и
`VALIDATOR_BACKEND=native`. Локальный запуск выбирает `GAMEFORGE_PROVIDER`, Compose —
`CONTAINER_PROVIDER`. Файл участника содержит оба варианта, но не заменяет весь `.env`:
переносите значения в существующие строки, не создавая дубликаты. Не меняйте свой токен
на токен коллеги: право читать сохранённые результаты связано с владельцем ключа.

Шаблон использует `DATABASE_URL=postgresql:///gameforge_mini` и
`REDIS_URL=redis://127.0.0.1:6379/0`. При других службах измените эти адреса.
URL реле — `https://129.101.114.59` без `/v1`. Лимиты контекста и ответа уже заданы
для текущей `qwen38`; загрузка модели локально не нужна.

`.env`, файлы токенов и `.data` не отправляйте в Git/общий чат. Не добавляйте секреты
в `VITE_*`: эти переменные могут попасть в браузерную сборку.

## 4. Запустите приложение

Порты **8000 и 8001** должны быть свободны. Команды выполняются в корне проекта:

```sh
TZ=UTC .venv/bin/python scripts/dev.py start
TZ=UTC .venv/bin/python scripts/dev.py status
curl --fail http://127.0.0.1:8000/api/health/
```

Менеджер проверит браузер, применит миграции, создаст первого администратора, затем
запустит Django, preview, Celery worker и beat. Повторный bootstrap не меняет пароль
существующего пользователя. Откройте **http://127.0.0.1:8000/** и войдите данными `.env`.
Preview использует другой origin **http://localhost:8001/**; корень preview отвечает 404,
игра открывается по конкретной ссылке из приложения. Открывайте приложение через `127.0.0.1`.

Проверка реле и токена **без генерации**, из другого терминала в той же папке:

```sh
.venv/bin/python - <<'PY'
from dotenv import load_dotenv
load_dotenv('.env')
from generation.providers.relay import configuration
from generation.relay_api.client import Client
url, token = configuration()
client = Client(url, token)
try:
    assert client.call('GET', '/health').get('protocol') == 1
finally:
    client.close()
print('Relay TLS/auth OK')
PY
```

Успех подтверждает TLS и доступ к реле, но не наличие свободной GPU. Общая очередь
участников нормальна. После проверок можно отправить небольшой запрос в интерфейсе.

## 5. Логи, остановка, перезапуск и обновление

```sh
tail -f .data/app.log .data/preview.log .data/worker.log .data/beat.log
.venv/bin/python manage.py diagnose_invocation
```

`Ctrl+C` прекращает просмотр логов. Закрытие вкладки не отменяет генерацию, пока локальные
службы продолжают работать. Перед обновлением дождитесь окончания заданий или отмените
их явно. Не удаляйте PID-файл вручную, пока процессы живы.

```sh
TZ=UTC .venv/bin/python scripts/dev.py stop
TZ=UTC .venv/bin/python scripts/dev.py status
```

Если worker ещё завершает работу, дождитесь его остановки и повторите `stop`.
PostgreSQL и Redis менеджер не останавливает. Нативный браузер завершается после проверки.
Для перезапуска выполните `start`; изменения `.env` требуют полного stop/start.
Codex остаётся доступным: параметры переключения приведены в README, изоляция браузера
не зависит от выбранного модельного провайдера.

Перед обновлением сохраните БД (`pg_dump -Fc gameforge_mini`) и приватную `.env` в закрытую
папку. Сохраните свои Git-изменения, затем:

```sh
git pull --ff-only
.venv/bin/python -m pip install -r requirements-dev.lock
npm ci --prefix web
npm run build --prefix web
.venv/bin/python scripts/native.py prepare
TZ=UTC .venv/bin/python scripts/dev.py start
```

## Границы изоляции и диагностика

Нативный режим предназначен для локальной разработки доверенной командой. Это не
замена контейнерному развёртыванию публичного сервиса: в частности, здесь нет такого же
общего ограничения RAM/числа процессов, как в контейнерном профиле.

macOS использует deny-by-default Seatbelt, Linux/WSL2 — отдельные mount/PID/network/user
namespace [bubblewrap](https://github.com/containers/bubblewrap). Браузер получает только
среду исполнения и новую временную папку, без токенов/БД/домашнего каталога пользователя.
На macOS разрешены необходимые системные библиотеки и установленное ПО Homebrew;
сеть, личные документы и Keychain не разрешены. Дополнительно действуют ограничения
страницы, Playwright-маршрутов и времени проверки. Нет fallback без OS sandbox.

`scripts/native.py check` повторяет проверку без загрузки браузера и вызова модели.
Если есть `Operation not permitted`, ошибка `bwrap`, `sandbox-exec` или зависимостей
Chromium, сначала устраните её; не удаляйте защитные параметры. Для смены компьютера
не переносите `.venv` или браузерный кеш — установите их заново под нужную ОС/архитектуру.
Нативный режим проверен на macOS ARM64 и Ubuntu 22.04 в
[задании native-validator](https://github.com/HoshiBatista/webgame-agent/actions/runs/39974101956/job/120484098783).
WSL2 отдельно не проверялся; там требуется работающий bubblewrap с разрешёнными namespace.
