# Контекст для агента (AI)

**Читай этот файл в начале новой сессии.** В нём — состояние проекта, что сделано, что в процессе, что запланировано. Обновляй разделы по мере работы.

---

## Проект в двух словах

**Мультитаймфреймовый торговый бот для Bybit.** Цель: торговля с опорой на несколько таймфреймов (тренд со старшего, вход с младшего). Стек: Python, pybit, SQLite, .env-конфиг. Пара по умолчанию — фьючерс **BTCUSDT** (linear).

---

## Сделано (DONE)

- **Структура src/** — слоистая архитектура: **core/** (инфраструктура), **analysis/** (аналитика), **app/** (приложения), **scripts/** (скрипты). Импорты между пакетами — относительные (`from ..core import config` и т.д.). Запуск через launcher-ы в корне: `main.py` → `src.app.main`, `telegram_bot.py` → `src.app.telegram_bot`, остальные — из `src.scripts.*`.
- **src/core/** — конфиг, БД, биржа. **config.py**: загрузка .env из корня (PROJECT_ROOT), `validate_config()`. **database.py**: SQLite, таблица `klines`, init_db, get_connection, insert_candles, get_candles, get_latest/oldest_start_time, count_candles. **exchange.py**: Bybit REST V5 — get_klines, get_klines_multi_timeframe, fetch_klines_backfill.
- **src/analysis/** — аналитика. **market_phases.py**: 6 фаз (accumulation, markup, distribution, markdown, capitulation, recovery), `detect_phase(...)` по OHLCV → phase, phase_ru, score, details; динамический score, RSI, объём у границ, дивергенция, Spring/Upthrust, сила тренда, свежесть зоны, контекст старшего ТФ. **multi_tf.py**: запрос свечей по TIMEFRAMES, тренд по ТФ, фаза по каждому ТФ, сигнал long/short/none по старшему ТФ.
- **src/app/** — приложения. **main.py**: только цикл и запуск — валидация конфига, db_sync, в цикле bot_loop.run_one_tick() и sleep. **bot_loop.py**: один тик — refresh_if_due + analyze_multi_timeframe + лог отчёта. **db_sync.py**: open_and_prepare, refresh_if_due, close. **telegram_bot.py**: команды /start, /help, /signal, /status, /db, /id; Reply-панель + inline-кнопки (Сигнал | БД | Обновить) под ответами; меню команд (set_my_commands); разбивка длинных сообщений; TELEGRAM_ALLOWED_IDS; обработка Conflict (409).
- **src/scripts/** — скрипты. **accumulate_db.py**: бэкфилл + периодическое дотягивание по TIMEFRAMES_DB. **backtest_phases.py**: бэктест точности фаз по БД, `--min-score`, `--tune`. **full_backfill.py**: полный бэкфилл за весь период Bybit. **test_run_once.py**: один прогон анализа для теста.
- **Корневые лаунчеры** — `main.py`, `telegram_bot.py`, `accumulate_db.py`, `backtest_phases.py`, `full_backfill.py`, `test_run_once.py` только поднимают sys.path и вызывают соответствующий модуль из `src.app` или `src.scripts`.
- **ДЛЯ_КОМАНДЫ.md** — онбординг: структура, файлы, связи, .env, как запускать.
- **release.py** — версии и выгрузка в GitHub. Откат: `git checkout v1.0.0`.
- БД в `data/klines.db`, по 13 ТФ (1,3,5,15,30,60,120,240,360,720,D,W,M), колонка `volume`.

---

## В процессе (IN PROGRESS)

- *Пока пусто. Сюда добавлять задачи, над которыми идёт работа.*

---

## Планируем (PLANNED)

- Индикаторы на выбранных ТФ (MA, RSI, уровни и т.п.).
- Исполнение ордеров через Bybit API по сигналу из multi_tf.
- Риск-менеджмент: размер позиции, стоп-лосс, тейк-профит.
- Использование БД для обучения моделей (чтение из klines по symbol/timeframe/диапазону).
- При желании — поддержка нескольких пар и отдельная конфигурация стратегии.

---

## Куда смотреть по задачам

| Задача | Файлы / места |
|--------|----------------|
| Пара, ТФ, лимиты, порог фазы (PHASE_SCORE_MIN) | src/core/config.py, .env |
| Запросы к Bybit, бэкфилл | src/core/exchange.py |
| Схема БД, вставка, выборки, get_candles | src/core/database.py |
| Накопление свечей | src/scripts/accumulate_db.py |
| 6 фаз рынка | src/analysis/market_phases.py |
| Бэктест точности фаз, --min-score, --tune | src/scripts/backtest_phases.py, backtest_phases.py (лаунчер) |
| Логика сигнала, тренды, агрегация по ТФ | src/analysis/multi_tf.py |
| Цикл и лог | src/app/main.py, main.py (лаунчер) |
| Полный бэкфилл за весь период | src/scripts/full_backfill.py, full_backfill.py (лаунчер) |
| Управление через Telegram | src/app/telegram_bot.py, telegram_bot.py (лаунчер); TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_IDS |
| Версии, теги, push в GitHub, откат | release.py (в корне) |
| Онбординг человека | ДЛЯ_КОМАНДЫ.md |
| Проверка работоспособности | check_all.py (в корне), `python check_all.py` |

---

## Важные договорённости

- Конфиг только из .env через config.py.
- Порог фазы для торгового решения: PHASE_SCORE_MIN (0..1). При score фазы старшего ТФ ниже него сигнал не считается подтверждённым фазой (direction может остаться none или «осторожно»). По умолчанию 0.5.
- Для чтения свечей ключи API не нужны; для сделок — нужны BYBIT_API_KEY/SECRET.
- По умолчанию BYBIT_TESTNET=true. Не коммитить .env.
- База — один SQLite-файл (DB_PATH), каталог data/ в .gitignore.
- Версии — теги git (v1.0.0 и т.п.), создаются через `python release.py X.Y.Z`. Откат — `git checkout vX.Y.Z`.

---

## Как обновлять этот файл

- Завершил фичу из PLANNED → перенеси в DONE, кратко что сделано.
- Начал задачу → добавь в IN PROGRESS с пометкой, что именно делаешь.
- Появилась новая цель → добавь в PLANNED.
- Менялась архитектура или соглашения → обнови «Куда смотреть» и «Важные договорённости».
