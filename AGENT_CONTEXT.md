# Контекст для агента (AI)

**Читай этот файл в начале новой сессии.** В нём — состояние проекта, что сделано, что в процессе, что запланировано. Обновляй разделы по мере работы.

---

## Проект в двух словах

**Мультитаймфреймовый торговый бот для Bybit.** Цель: торговля с опорой на несколько таймфреймов (тренд со старшего, вход с младшего). Стек: Python, pybit, SQLite, .env-конфиг. Пара по умолчанию — фьючерс **BTCUSDT** (linear).

---

## Сделано (DONE)

- **Структура src/** — слоистая архитектура: **core/** (инфраструктура), **analysis/** (аналитика), **app/** (приложения), **scripts/** (скрипты). Импорты между пакетами — относительные (`from ..core import config` и т.д.). Запуск через launcher-ы в корне: `main.py` → `src.app.main`, `telegram_bot.py` → `src.app.telegram_bot`, остальные — из `src.scripts.*`.
- **src/core/** — конфиг, БД, биржа. **config.py**: загрузка .env из корня (PROJECT_ROOT), `validate_config()`. **database.py**: SQLite, таблица `klines`, init_db, get_connection, insert_candles, get_candles, get_latest/oldest_start_time, count_candles, delete_klines_for_symbol, delete_klines_for_symbol_timeframe. **exchange.py**: Bybit REST V5 — get_klines, get_klines_multi_timeframe, fetch_klines_backfill; **_filter_valid_ohlc** — отсев свечей с нереалистичными ценами (для BTC 1k–500k USDT).
- **src/analysis/** — аналитика. **market_phases.py**: 6 фаз (Вайкофф + индикаторы) — структура, объём, Spring/Upthrust с подтверждением объёмом, Selling/Buying climax, EMA 20/50/200, ADX, BB width, OBV, VWAP, RSI, контекст старшего ТФ; при 200+ свечах окно 200; PHASE_PROFILES (short/long), подбор через `--tune`; phase_unclear, score_gap, secondary_phase; swing_levels для уровней поддержки/сопротивления. **market_trend.py**: detect_trend (структура, EMA-стек, ADX, сила тренда, VWAP, OBV, return 5/20), detect_regime (тренд/диапазон/всплеск по ADX, ATR, BB width). **multi_tf.py**: запрос свечей (из БД при DATA_SOURCE=db), проверка качества свечей (utils.candle_quality), тренд и режим по каждому ТФ (через market_trend), фаза по каждому ТФ, фильтры (объём, ATR, уровни, tf_align, regime_ok, качество свечей), phase_decision_ready, единый score входа (фаза + тренд + совпадение ТФ), сигнал long/short/none по старшему ТФ, confidence = entry_score. **phase_wyckoff.py**, **phase_indicators.py**, **phase_structure.py** — экспериментальные модули для сравнения методов.
- **src/app/** — приложения. **main.py**: только цикл и запуск — валидация конфига, db_sync, при заданном TELEGRAM_BOT_TOKEN запуск telegram_bot в отдельном потоке (общее соединение с БД), в цикле bot_loop.run_one_tick() и sleep. **bot_loop.py**: один тик — refresh_if_due + analyze_multi_timeframe + лог отчёта (в т.ч. режим, тренд по ТФ). **db_sync.py**: open_and_prepare, refresh_if_due, close. **telegram_bot.py**: команды /start, /help, /signal, /status, /db, **/chart** (свечной график с трендами Вверх/Вниз/Флэт из БД), /backtest_phases, /id; Reply-панель + inline-кнопки (Сигнал | БД | Обновить); меню команд (set_my_commands); разбивка длинных сообщений; TELEGRAM_ALLOWED_IDS; обработка Conflict (409); при вызове из main — принимает db_conn.
- **src/scripts/** — скрипты. **accumulate_db.py**: бэкфилл + дотягивание по TIMEFRAMES_DB, run_extend_until_done при AUTO_EXTEND_AT_STARTUP. **backtest_phases.py**: бэктест точности фаз по БД, `--min-score`, `--tune`. **backtest_trend.py**: бэктест точности модуля тренда (market_trend; только CLI, не в Telegram). **compare_phase_methods.py**: сравнение трёх методов фаз (Wyckoff / Indicators / Structure). **full_backfill.py**: полный бэкфилл за весь период Bybit. **refill_tf_d.py**: перезалив только ТФ D с биржи (удаление + загрузка с фильтром цен). **test_run_once.py**: один прогон анализа.
- **Корневые лаунчеры** — `main.py` (при TELEGRAM_BOT_TOKEN поднимает и Telegram-бота), `telegram_bot.py`, `accumulate_db.py`, `backtest_phases.py`, `backtest_trend.py`, `compare_phase_methods.py`, `full_backfill.py`, **refresh_db.py** (удаление БД + полный бэкфилл по всем ТФ), **refill_tf_d.py**, **catch_up_db.py** (догрузка БД до текущей даты), `test_run_once.py` поднимают sys.path и вызывают модули из `src.app` или `src.scripts`.
- **Реализовано:** **strategies/** (заготовка), **tests/** (unit/, integration/, backtest/), **src/utils/** (validators, helpers, candle_quality, **backtest_chart** — build_phases_chart, build_trend_chart, build_candlestick_trend_chart: свечной график с трендами Вверх/Вниз/Флэт, коррекция масштаба для BTC, отсев нереалистичных дневных свечей), **src/core/logging_config.py**.
- **Cursor:** правила в **.cursorrules** (корень) и **.cursor/rules/** (trading-bot.mdc). AI читает контекст и соглашения оттуда.
- **ДЛЯ_КОМАНДЫ.md** — онбординг: структура, файлы, связи, .env, как запускать.
- **release.py** — версии и выгрузка в GitHub. Откат: `git checkout v1.0.0`.
- БД в `data/klines.db`, по 13 ТФ (1,3,5,15,30,60,120,240,360,720,D,W,M), колонка `volume`.

---

## В процессе (IN PROGRESS)

- *Пока пусто. Сюда добавлять задачи, над которыми идёт работа.*

---

## Планируем (PLANNED)

- Фазы уже используют индикаторы (EMA, ADX, BB, OBV, VWAP, RSI) и Вайкофф. Дальше — тонкая настройка порогов и стратегий.
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
| Сравнение методов фаз (Wyckoff / Indicators / PA) | src/scripts/compare_phase_methods.py, compare_phase_methods.py (лаунчер) |
| 6 фаз (эксперимент: только Вайкофф / только индикаторы / только PA) | src/analysis/phase_wyckoff.py, phase_indicators.py, phase_structure.py |
| Логика сигнала, единый score входа, тренды, режим, фильтры, качество свечей, агрегация по ТФ | src/analysis/multi_tf.py |
| Модуль тренда и режима (detect_trend, detect_regime) | src/analysis/market_trend.py |
| Проверка качества свечей (OHLCV, валидность) | src/utils/candle_quality.py |
| Цикл и лог | src/app/main.py, main.py (лаунчер) |
| Полный бэкфилл за весь период | src/scripts/full_backfill.py, full_backfill.py (лаунчер) |
| Управление через Telegram, /chart (свечной график с трендами) | src/app/telegram_bot.py, telegram_bot.py (лаунчер); TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_IDS |
| Визуализация графиков (фазы, тренд, свечной с трендами) | src/utils/backtest_chart.py |
| Полное обновление БД (удаление + загрузка всех ТФ) | refresh_db.py (в корне), `python refresh_db.py [--yes]` |
| Перезалив ТФ D, догрузка БД до текущей даты | refill_tf_d.py, catch_up_db.py (в корне) |
| Версии, теги, push в GitHub, откат | release.py (в корне) |
| Онбординг человека | ДЛЯ_КОМАНДЫ.md |
| Проверка работоспособности, выбросы цен в БД (BTC) | check_all.py (в корне), `python check_all.py [--quick] [-v]` |

---

## Важные договорённости

- Конфиг только из .env через config.py.
- Порог фазы: PHASE_SCORE_MIN, PHASE_UNCLEAR_THRESHOLD, PHASE_MIN_GAP, PHASE_STABILITY_MIN, PHASE_HISTORY_SIZE. Тренд: TREND_STRENGTH_MIN, TREND_UNCLEAR_THRESHOLD, TREND_MIN_GAP, TREND_STABILITY_MIN. Фильтры входа: VOLUME_MIN_RATIO, ATR_MAX_RATIO, TF_ALIGN_MIN, LEVEL_MAX_DISTANCE_PCT, REGIME_BLOCK_SURGE. Единый score входа: ENTRY_SCORE_WEIGHT_PHASE, ENTRY_SCORE_WEIGHT_TREND, ENTRY_SCORE_WEIGHT_TF_ALIGN. Качество свечей: CANDLE_QUALITY_MIN_SCORE (0 = не блокировать).
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
