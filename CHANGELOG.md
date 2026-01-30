# История изменений

Все значимые изменения в проекте описаны в этом файле.

---

## [Unreleased]

- *(пока пусто)*

---

## [2.6.0] — 2026-01-30

Структура bin/, конфиг на pydantic-settings, улучшения тренда, визуализация и тесты тренда, проверка скриптов в check_all.

### Добавлено

- **Структура bin/:** все лаунчеры БД и бэктестов перенесены в `bin/`; запуск из корня: `python bin/catch_up_db.py`, `python bin/accumulate_db.py` и т.д. В корне остаются `main.py`, `telegram_bot.py`, `check_all.py`, `release.py`. Добавлен **STRUCTURE.md** — карта проекта.
- **Конфиг на pydantic-settings:** `src/core/config.py` переписан на `BaseSettings` (типизация, валидация из `.env`). В `requirements.txt` добавлен `pydantic-settings`.
- **Тренд по всей БД ТФ D:** скрипт `bin/trend_daily_full.py` и `src/scripts/trend_daily_full.py` — загрузка всех D-свечей из БД, расчёт тренда по полной истории, график с зонами Вверх/Вниз/Флэт (`build_daily_trend_full_chart` в backtest_chart). В Telegram — команда `/trend_daily`.
- **Отчёт по бэктесту тренда:** `bin/trend_backtest_report.py`, `src/scripts/trend_backtest_report.py` — график точности по направлениям (Вверх/Вниз/Флэт).
- **Тесты тренда:** юнит-тесты `tests/unit/test_market_trend.py`; проверка точности на ТФ D `tests/backtest/test_trend_accuracy.py`.
- **check_all:** в проверку скриптов добавлены `trend_daily_full`, `trend_backtest_report`; экспорт в `src/scripts/__init__.py`.

### Изменено

- **Алгоритм тренда (market_trend):** усилены веса return_5/return_20, метрика силы тренда, адаптация по ТФ (TREND_PROFILES short/long), ужесточено условие «вниз» (TREND_MIN_GAP_DOWN). В конфиг добавлены TREND_FLAT_WHEN_RANGE, TREND_MIN_GAP_DOWN, TREND_USE_PROFILES.
- **БД (database.py):** включён режим WAL (`PRAGMA journal_mode=WAL`), `PRAGMA busy_timeout=5000`.
- **Exchange:** для ТФ D/W/M порог интрадей-диапазона увеличен до 50%; таймаут запросов задаётся через EXCHANGE_REQUEST_TIMEOUT_SEC в конфиге.
- **Документация:** README, AGENT_CONTEXT, ДЛЯ_КОМАНДЫ, STRUCTURE, bin/README — актуализированы пути (bin/), скрипты тренда, команды Telegram (/trend_daily).

---

## [2.5.0] — 2026-01-30

Промежуточная версия: модуль db_helper, дозаполнение пропусков в БД, график «последние 2 года» без искажений.

### Добавлено

- **Модуль db_helper (src/core/db_helper.py):** умные выборки по БД — проверка актуальности (`is_stale`), догрузка одного ТФ (`catch_up_tf`), выборка за последние N дней (`get_candles_last_days`) с кэшем 60 с; `ensure_fresh_then_get` — при устаревших данных догружает ТФ, при малом числе свечей (<60% от запрошенного) один раз дозаполняет пропуски и перезапрашивает. Лимит выборки для 730 дней увеличен до 2000 свечей.
- **Дозаполнение пропусков:** в `accumulate_db` — `run_fill_gap_for_timeframe()` (загрузка диапазона между самой старой и самой новой свечой по ТФ); лаунчер `fill_gap_db.py` — дозаполнение по всем ТФ из TIMEFRAMES_DB (`python fill_gap_db.py`).
- **График /chart:** по умолчанию «последние 2 года» (730 дневных свечей), отображение фактического периода данных в подписи; использование `db_helper.ensure_fresh_then_get` для актуальных данных без полной перезаливки БД.

### Изменено

- **Свечной график (backtest_chart):** по умолчанию без зон трендов (`show_trends=False`), без коррекции масштаба (`scale_correction=False`) — реальные цены как в TradingView; фильтр цен для BTC 1k–150k USDT, макс. интрадей-диапазон (high-low)/open 30%; жёсткий отсев по последним 730 дням от последней свечи.
- **Exchange:** фильтр цен для BTCUSDT сужен до 1k–150k USDT; `_MAX_OHLC_RANGE_RATIO` 30% для отсева абсурдных свечей.
- **Telegram /chart:** интеграция с db_helper, limit 730 свечей, подпись с периодом данных.

---

## [2.4.0] — 2026-01-30

Промежуточная версия: полное обновление БД, свечной график с трендами в Telegram, фильтр цен, проверка выбросов.

### Добавлено

- **Полное обновление БД:** скрипт `refresh_db.py` — удаление файла БД и загрузка всех таймфреймов из TIMEFRAMES_DB с биржи (`python refresh_db.py [--yes]`). Перед запуском останови бота.
- **Перезалив ТФ D:** скрипт `refill_tf_d.py` — удаление свечей по паре и ТФ D и загрузка истории заново с Bybit (с фильтром нереалистичных цен).
- **Догрузка БД до текущей даты:** скрипт `catch_up_db.py` — подтягивает пропущенные свечи по всем ТФ из TIMEFRAMES_DB.
- **Свечной график с трендами в Telegram:** команда `/chart` — график из БД (ТФ D, до 1500 свечей) с зонами трендов Вверх/Вниз/Флэт (build_candlestick_trend_chart в src/utils/backtest_chart.py). В инфобоксе — дата последней свечи. Для BTC: коррекция масштаба при завышенных/смешанных данных; отсев нереалистичных дневных свечей (движение за день >50%).
- **Фильтр цен в exchange:** `_filter_valid_ohlc()` — отсев свечей с нереалистичными OHLC (для BTCUSDT: 1000–500 000 USDT). Применяется ко всем ответам get_klines и fetch_klines_backfill.
- **Проверка выбросов цен в check_all:** «БД: выбросы цен (BTC)» — подсчёт свечей с high/close > 100k по ТФ; предупреждение и подсказка перезалить данные.

### Изменено

- **Telegram-бот:** команда `/backtest_trend` удалена из меню и обработчиков (скрипт backtest_trend.py остаётся для CLI).
- **README, AGENT_CONTEXT, ДЛЯ_КОМАНДЫ:** актуализированы структура, скрипты (refresh_db, refill_tf_d, catch_up_db), команды Telegram (/chart), exchange (filter_valid_ohlc), database (delete_klines_for_symbol_timeframe), backtest_chart.

---

## [2.3.0] — 2026-01-28

Промежуточная версия: тренд и режим рынка, единый score входа, качество свечей, расширенный check_all, Telegram (режим/score/качество).

### Добавлено

- **Модуль тренда и режима рынка (market_trend.py):** `detect_trend()` — агрегация структуры (HH/HL, LH/LL), EMA-стек, ADX (+DI/-DI), силы тренда, VWAP, OBV slope, return 5/20; возвращает direction (up/down/flat), strength, trend_unclear, secondary_direction, strength_gap. `detect_regime()` — режим рынка (тренд/диапазон/всплеск) по ADX, ATR и ширине Bollinger Bands.
- **Режим рынка в multi_tf:** по каждому ТФ считается режим (trend/range/surge); по старшему ТФ — фильтр `REGIME_BLOCK_SURGE` (1 = не входить при режиме «всплеск»). В отчёт и лог добавлены higher_tf_regime, regime_ru, regime_ok, по ТФ — regime, regime_ru.
- **Фильтры входа в phase_decision_ready:** объём относительно MA(vol) — `VOLUME_MIN_RATIO`; ATR относительно MA(ATR) — `ATR_MAX_RATIO`; расстояние цены до свинг-уровней — `LEVEL_MAX_DISTANCE_PCT`; минимум ТФ, совпадающих по тренду и фазе со старшим — `TF_ALIGN_MIN`; устойчивость фазы и тренда (PHASE_STABILITY_MIN, TREND_STABILITY_MIN, PHASE_HISTORY_SIZE).
- **Усиление фаз:** phase_unclear, score_gap, secondary_phase; свинг-уровни (swing_levels) для поддержки/сопротивления; конфиг PHASE_UNCLEAR_THRESHOLD, PHASE_MIN_GAP.
- **Telegram-бот из main.py:** при заданном TELEGRAM_BOT_TOKEN бот запускается в отдельном потоке с общим соединением с БД; отдельный процесс `python telegram_bot.py` по-прежнему поддерживается.
- **Бэктест тренда:** скрипт `backtest_trend.py` (лаунчер в корне) для проверки точности модуля тренда по БД.
- **Единый score входа (0..1):** взвешенная сумма фазы старшего ТФ, силы тренда и доли совпадающих ТФ; бонус за устойчивость. Конфиг: ENTRY_SCORE_WEIGHT_PHASE, ENTRY_SCORE_WEIGHT_TREND, ENTRY_SCORE_WEIGHT_TF_ALIGN. confidence в сигнале = entry_score при наличии направления.
- **Проверка качества свечей:** модуль `src/utils/candle_quality.py` — валидация OHLCV (структура, OHLC-логика, NaN/None, объём). В multi_tf по каждому ТФ используются отфильтрованные свечи; при CANDLE_QUALITY_MIN_SCORE > 0 низкое качество блокирует phase_decision_ready.

### Изменено

- **multi_tf.py** — тренд по ТФ через `detect_trend()` (market_trend); режим по ТФ через `detect_regime()`; phase_decision_ready учитывает фильтры объёма, ATR, уровней, совпадения ТФ, режима «всплеск» и устойчивость фазы/тренда; в отчёт добавлены regime, trend_stability, phase_stability, filters_ok, tf_align_ok, regime_ok.
- **bot_loop.py** — в лог добавлены режим по старшему ТФ и по каждому ТФ.
- **config.py** — добавлены VOLUME_MIN_RATIO, ATR_MAX_RATIO, TF_ALIGN_MIN, TREND_STABILITY_MIN, LEVEL_MAX_DISTANCE_PCT, REGIME_BLOCK_SURGE, ENTRY_SCORE_WEIGHT_*, CANDLE_QUALITY_MIN_SCORE; пороги фаз и тренда (PHASE_UNCLEAR_THRESHOLD, PHASE_MIN_GAP, PHASE_STABILITY_MIN, PHASE_HISTORY_SIZE, TREND_*).
- **multi_tf.py** — единый entry_score, проверка качества свечей по каждому ТФ, candle_quality_ok в phase_decision_ready.
- **Документация** — AGENT_CONTEXT.md, ДЛЯ_КОМАНДЫ.md, README.md актуализированы: модуль тренда, режим рынка, фильтры, единый score, качество свечей, запуск Telegram из main, backtest_trend, таблица .env.
- **check_all.py** — проверки порогов (CANDLE_QUALITY_MIN_SCORE, веса entry_score, TF_ALIGN_MIN), структуры отчёта multi_tf (entry_score, higher_tf_regime, candle_quality_ok), модулей анализа (market_trend, candle_quality), скриптов (backtest_trend, compare_phase_methods).

---

## [2.2.0] — 2026-01-28

Промежуточная версия: метрики фаз (EMA, ADX, BB, OBV, VWAP), усиление Вайкоффа, три модуля фаз для сравнения.

### Добавлено

- **Метрики фаз (market_phases):** EMA 20/50/200 (стек), ADX(14), ширина Bollinger Bands, OBV slope, VWAP (rolling). Учёт в решении о фазе и в details.
- **Усиление Вайкоффа:** при 200+ свечах окно 200 баров (для EMA200); Spring/Upthrust с подтверждением объёмом; Selling/Buying climax; счёт подтверждений для markup/markdown (2+ или 3+ из четырёх индикаторов дают бонус к score).
- **Подбор порогов (--tune):** для профиля long обновлены PHASE_PROFILES (vol_spike 1.5, drop_threshold -0.07, range_position_high 0.70).
- **Три модуля фаз для сравнения:** phase_wyckoff (только Вайкофф), phase_indicators (только индикаторы), phase_structure (только price action / BOS-CHOCH). Единый интерфейс detect_phase().
- **Скрипт сравнения методов:** compare_phase_methods.py — один бэктест по БД для трёх методов, вывод точности по направлению. Лаунчер в корне.

### Изменено

- **market_phases.py** — детектор фаз расширен (см. выше); details дополнены полями ema_trend, adx, bb_width, obv_slope, vwap_distance, spring_volume_confirmed, upthrust_volume_confirmed, selling_climax, buying_climax.
- **ДЛЯ_КОМАНДЫ.md**, **README.md**, **AGENT_CONTEXT.md** — актуализированы структура, описание фаз, скрипты и лаунчеры.

---

## [2.1.0] — 2026-01-28

Промежуточная версия: анализ из БД, ретраи API, уверенность сигнала, расширенный check_all.

### Добавлено

- **Источник свечей для анализа (DATA_SOURCE)** — при `db` анализ читает из локальной БД (меньше запросов к Bybit), при `exchange` — запрос на каждый тик. По умолчанию `db`. В `analyze_multi_timeframe` добавлены аргументы `data_source` и `db_conn`.
- **Ретраи и учёт rate limit в exchange** — обёртка `_request_kline()` с повторными попытками при кодах 10006/10007, таймаутах и сетевых сбоях. Настройки `EXCHANGE_MAX_RETRIES`, `EXCHANGE_RETRY_BACKOFF_SEC` в .env.
- **Уверенность сигнала** — в ответе `signals` добавлены `confidence` (0..1), `confidence_level` (weak/medium/strong), `above_min_confidence`. Порог задаётся через `SIGNAL_MIN_CONFIDENCE`. Отображается в логах, в `signals.log` и в Telegram (/signal, /status).
- **Расширенный check_all.py** — 14 проверок: .env, конфиг и пороги, соответствие TIMEFRAMES и TIMEFRAMES_DB при DATA_SOURCE=db, БД и подсчёт по ТФ, пинг Bybit, multi_tf с биржи и из БД, логирование, ретраи, Telegram, скрипты, модули app. Флаги `--quick` (без сетевых проверок) и `-v` (тайминги и детали).

### Изменено

- **multi_tf** — при переданном `db_conn` и `DATA_SOURCE=db` загрузка свечей из БД через `_load_candles_from_db()`.
- **bot_loop** — вызов `analyze_multi_timeframe(db_conn=db_conn)`; в лог и в signals.log добавлены confidence и confidence_level.
- **Telegram-бот** — передача `db_conn` в запросы сигнала/статуса через `bot_data`, отображение уверенности в ответах.
- В **config** добавлены `DATA_SOURCE`, `SIGNAL_MIN_CONFIDENCE`, `EXCHANGE_MAX_RETRIES`, `EXCHANGE_RETRY_BACKOFF_SEC`. В `.env.example` и ДЛЯ_КОМАНДЫ.md — описание новых переменных.

---

## [2.0.0] — 2026-01-28

### Чем отличается от v1.0.0

**Автоматическое углубление истории по всем таймфреймам**

- При каждом старте бота (`main.py`, `telegram_bot.py`) после бэкфилла и догрузки пропусков по всем ТФ из `TIMEFRAMES_DB` автоматически подгружается история вглубь, пока API отдаёт свечи.
- Не нужно вручную запускать `python full_backfill.py --extend`, в том числе для таймфрейма 3m и других «отстающих» ТФ.
- Включено по умолчанию; отключить: в `.env` задать `AUTO_EXTEND_AT_STARTUP=0`.

**Единая система логирования**

- Все события пишутся в каталог `logs/` (по умолчанию в корне проекта):
  - **bot.log** — полный лог с модулем, функцией и номером строки; ротация по размеру (до 10 МБ, 7 файлов).
  - **signals.log** — по одной короткой строке на каждый тик: направление, причина, тренд и фаза старшего ТФ (удобно для разбора и статистики).
- Настройки в `.env`: `LOG_DIR`, `LOG_LEVEL`, `LOG_LEVEL_FILE`, `LOG_FILE_MAX_MB`, `LOG_BACKUP_COUNT`, `LOG_SIGNALS_FILE`.
- Логирование подключается при старте `main`, `telegram_bot`, `accumulate_db`, `full_backfill`.

**Прочее**

- Удалены лишние файлы: `run_main.bat`, `run_accumulate_db.bat`, `run_telegram_bot.bat` (запуск по-прежнему через `python main.py` и т.п.).
- В документацию (ДЛЯ_КОМАНДЫ.md, .env.example) добавлены описание авто-углубления, переменных логирования и раздела «Логирование».
- В `.gitignore` добавлен каталог `logs/`.

### Добавлено

- `src/core/logging_config.py` — настройка логирования: `setup_logging()`, `get_signals_logger()`.
- В `src/core/config.py`: `AUTO_EXTEND_AT_STARTUP`, `LOG_DIR`, `LOG_LEVEL`, `LOG_LEVEL_FILE`, `LOG_FILE_MAX_MB`, `LOG_BACKUP_COUNT`, `LOG_SIGNALS_FILE`.
- В `src/scripts/accumulate_db.py`: `run_extend_backward_one_chunk()`, `run_extend_until_done()`; вызов `setup_logging()` в `main()`.
- В `src/app/db_sync.py`: при `AUTO_EXTEND_AT_STARTUP=1` вызов `run_extend_until_done(conn)` в `open_and_prepare()`.
- Запись одного тика в `signals.log` из `bot_loop._log_report()`.

### Изменено

- Точки входа `main.py`, `telegram_bot.py`, скрипты `accumulate_db`, `full_backfill` используют `setup_logging()` вместо разрозненного `logging.basicConfig(...)`.

### Удалено

- `run_main.bat`, `run_accumulate_db.bat`, `run_telegram_bot.bat`.

---

## [1.0.0] — базовая версия

- Мультитаймфреймовый анализ и сигнал (тренд старшего ТФ, 6 фаз рынка).
- Telegram-бот: команды `/start`, `/signal`, `/status`, `/db`, `/id`, `/help`, inline-кнопки, ограничение по `TELEGRAM_ALLOWED_IDS`.
- Накопление БД: бэкфилл по пустым ТФ, догрузка пропусков, периодическое обновление.
- Полный бэкфилл: `full_backfill.py [--clear] [--extend]`.
- Бэктест фаз и тест-прогон.
- Структура: `src/core`, `src/analysis`, `src/app`, `src/scripts`; лаунчеры в корне.
- Конфиг через `.env`, проверка через `check_all.py`.

[Unreleased]: https://github.com/TinyThief/best_bot_in_the_world/compare/v2.3.0...HEAD
[2.0.0]: https://github.com/TinyThief/best_bot_in_the_world/compare/v1.0.0...v2.0.0
[2.1.0]: https://github.com/TinyThief/best_bot_in_the_world/compare/v2.0.0...v2.1.0
[2.2.0]: https://github.com/TinyThief/best_bot_in_the_world/compare/v2.1.0...v2.2.0
[2.3.0]: https://github.com/TinyThief/best_bot_in_the_world/compare/v2.2.0...v2.3.0
[1.0.0]: https://github.com/TinyThief/best_bot_in_the_world/releases/tag/v1.0.0
