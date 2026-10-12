# Соответствие кейсу Билайн

Источник требований — `Keys_Bilayn.pdf`, 2 страницы. Матрица отделяет
реализованное поведение от того, что требует организационного действия или
production-инфраструктуры.

## Обязательные требования

| Требование | Реализация | Статус |
| --- | --- | --- |
| Текстовый естественноязыковой prompt | Поле ввода, примеры prompts, `POST /v1/projects` | Реализовано |
| Генерация кода через LLM, не зашитая игра | Два schema-constrained вызова OpenAI Responses API: `GameSpec`, затем полный HTML; модель `gpt-6-luna` | Реализовано |
| Начало → gameplay → победа/поражение → restart | Обязательные инструкции, static rules, bridge, browser input smoke-test и bounded repair | Реализовано; результат конкретной игры определяется её report |
| Self-contained HTML5 для WebView | Один `index.html`, inline CSS/JS/Canvas, сеть запрещена, CSP при preview | Реализовано |
| Команда 2–4 человека | Не является свойством кода | Подтверждается командой |
| Git с историей разработки | Репозиторий содержит историю коммитов | Есть; новые изменения нужно коммитить осмысленно |
| Презентация 3–5 минут | UI показывает prompt, live pipeline, preview и статус проверок | Сценарий демо готов; выступление остаётся команде |
| Использование ИИ | GPT-6 Luna работает внутри продуктового pipeline | Реализовано |

## Бонусные требования

| Бонус | Реализация | Статус |
| --- | --- | --- |
| Адаптация под аудиторию | `GameSpec.audience` + accessibility, правила размера UI, темпа и контраста | Реализовано |
| Аналитика прошлых игр | Host принимает start/win/lose/restart/share, PostgreSQL агрегирует по жанру и передаёт агрегаты в specification | Реализовано на уровне MVP |
| Итеративная доработка | `POST /v1/revisions/{id}/revise`, parent lineage, предыдущий HTML + новая инструкция | Реализовано |
| Генерация ассетов | Luna генерирует procedural Canvas-графику и WebAudio внутри self-contained игры | Частично: отдельная image/audio model pipeline отложена |
| Touch и адаптивность | Pointer Events/touch, resize и DPR — release rules; Playwright проверяет mobile viewport | Реализовано |
| История/галерея/share | Проекты и ревизии в PostgreSQL, gallery UI, публичный случайный slug | Реализовано |
| Разные жанры | Typed genres: arcade, puzzle, clicker, platformer, runner, other; механика генерируется из prompt | Реализовано архитектурно; качество измеряется golden suite |

## Сценарий демо

1. Ввести «Змейка для бабушки: крупные кнопки, медленный темп и высокий контраст».
2. Показать specification → Luna generation → mobile playtest.
3. Сыграть в validated preview с клавиатуры и touch-эмуляцией.
4. Попросить «сделай кнопки больше и добавь второй уровень» и показать child revision.
5. Скопировать публичную ссылку, открыть gallery/history и validation report.

Игру нельзя называть validated, если browser report имеет статус `unverified`
или `failed`. Отсутствие Chromium/API-доступа является честной ошибкой pipeline,
а не поводом пропустить gate.
