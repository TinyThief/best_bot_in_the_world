# Контекст для агента (AI)

**Читай этот файл в начале новой сессии.** В нём — состояние проекта, что сделано, что в процессе, что запланировано. Обновляй разделы по мере работы.

---

## Проект в двух словах

**Мультитаймфреймовый торговый бот для Bybit.** Цель: торговля с опорой на несколько таймфреймов (тренд со старшего, вход с младшего). Стек: Python, pybit, SQLite, .env-конфиг. Пара по умолчанию — фьючерс **BTCUSDT** (linear).

---

## Подход: решение по текущему состоянию рынка (prop-style)

Система принимает решение **только на основе снимка состояния «здесь и сейчас»** по каждому таймфрейму:

- **Что учитывается:** тренд, фаза рынка, режим (тренд/диапазон/всплеск), импульс, торговые зоны (цена у поддержки/сопротивления/в коридоре), совпадение ТФ, качество свечей.
- **Что не используется в момент решения:** форвард-доходность, исторические паттерны «что было после такого в прошлом», бэктестовая статистика в реальном времени.

На каждом тике загружаются **последние N свечей** по каждому ТФ, по ним считаются индикаторы и агрегируется сигнал. В отчёт добавляются **market_state_narrative** (краткое описание «что происходит сейчас») и **decision_basis: current_snapshot**, чтобы явно показывать: решение принято по текущему снимку рынка на всех ТФ.

---

## Сделано (DONE)

- **Структура src/** — слоистая архитектура: **core/** (инфраструктура), **analysis/** (аналитика), **app/** (приложения), **scripts/** (скрипты). Импорты между пакетами — относительные (`from ..core import config` и т.д.). Запуск через launcher-ы в корне: `main.py` → `src.app.main`, `telegram_bot.py` → `src.app.telegram_bot`, остальные — из `src.scripts.*`.
- **src/core/** — конфиг, БД, биржа. **config.py**: загрузка .env из корня (PROJECT_ROOT), `validate_config()`, ORDERBOOK_LIMIT (глубина стакана), ORDERFLOW_SAVE_TO_DB (запись метрик микроструктуры в БД). **database.py**: SQLite, таблица `klines`, таблица **orderflow_metrics** (метрики Order Flow: imbalance_ratio, delta, volume_per_sec, last_sweep_side и т.д.); insert_orderflow_metrics, get_orderflow_metrics; init_db, get_connection, insert_candles, get_candles, get_latest/oldest_start_time, count_candles, delete_klines_for_symbol, delete_klines_for_symbol_timeframe. **exchange.py**: Bybit REST V5 — get_klines, get_klines_multi_timeframe, fetch_klines_backfill; **get_orderbook** — REST-снимок стакана (bids/asks), ретраи при rate limit. **orderbook_ws.py**: WebSocket-стакан в реальном времени (OrderbookStream, start/stop, get_snapshot). **_filter_valid_ohlc** — отсев свечей с нереалистичными ценами (для BTC 1k–150k USDT) и абсурдным (high-low)/open > 30%. **db_helper.py**: умные выборки по БД — is_stale, catch_up_tf, get_candles_last_days (кэш 60 с), ensure_fresh_then_get (догрузка при устаревании, дозаполнение пропусков при малом числе свечей).
- **src/analysis/** — аналитика. **market_phases.py**: 6 фаз (Вайкофф + индикаторы) — структура, объём, Spring/Upthrust с подтверждением объёмом, Selling/Buying climax, EMA 20/50/200, ADX, BB width, OBV, VWAP, RSI, контекст старшего ТФ; при 200+ свечах окно 200; PHASE_PROFILES (short/long), подбор через `--tune`; phase_unclear, score_gap, secondary_phase; swing_levels для уровней поддержки/сопротивления. **market_trend.py**: detect_trend (структура, EMA-стек, ADX, сила тренда, VWAP, OBV, return 5/20), detect_regime (тренд/диапазон/всплеск по ADX, ATR, BB width), detect_momentum (состояние/направление, RSI, return_5). **trading_zones.py**: торговые зоны — свинг-пивоты, кластеризация уровней, переключение ролей (сопротивление после пробоя вверх → поддержка и наоборот); volume_at_level, confluence по ТФ; detect_trading_zones() возвращает уровни, nearest_support/resistance, zone_low/zone_high, in_zone, recent_flips, levels_with_confluence. **multi_tf.py**: **параллельный расчёт по ТФ** (ThreadPoolExecutor: quality, trend, phase без контекста, regime, momentum); запрос свечей (из БД при DATA_SOURCE=db); последовательно — обновление истории устойчивости, контекст старшего ТФ, **торговые зоны по старшему ТФ** (detect_trading_zones) и confluence по другим ТФ; фильтры (объём, ATR, уровни по зонам/свингам, tf_align, regime_ok, качество свечей); phase_decision_ready; единый score входа; сигнал long/short/none; confidence = entry_score. **phase_wyckoff.py**, **phase_indicators.py**, **phase_structure.py** — экспериментальные модули.
- **src/app/** — приложения. **main.py**: только цикл и запуск — валидация конфига, db_sync, при заданном TELEGRAM_BOT_TOKEN запуск telegram_bot в отдельном потоке (общее соединение с БД), в цикле bot_loop.run_one_tick() и sleep. **bot_loop.py**: один тик — refresh_if_due + analyze_multi_timeframe + лог отчёта (режим, тренд по ТФ, торговые зоны, импульс по старшему ТФ). **db_sync.py**: open_and_prepare, refresh_if_due, close. **telegram_bot.py**: команды /start, /help, /signal, /status, **/zones**, **/zones_chart**, **/zones_1h**, **/momentum**, /db, **/health**, /chart, /phases, /trend_daily, **/trend_backtest**, **/trade_2025** [год], /backtest_phases, /id; Reply-панель; inline-кнопки: **Сигнал | Зоны | Импульс** и Обновить | БД; обогащённый /signal (зоны, импульс, entry_score_breakdown); **алерт при смене сигнала** (TELEGRAM_ALERT_*); меню команд; разбивка длинных сообщений; TELEGRAM_ALLOWED_IDS; при вызове из main — принимает db_conn.
- **src/scripts/** — скрипты. **accumulate_db.py**: бэкфилл + дотягивание по TIMEFRAMES_DB, run_extend_until_done при AUTO_EXTEND_AT_STARTUP. **backtest_phases.py**: бэктест точности фаз по БД, `--min-score`, `--tune`. **backtest_trend.py**: бэктест точности модуля тренда (market_trend; только CLI). **backtest_trade_2025.py**: бэктест сценария управления сделкой за один год — сигнал по тренду (detect_trend), TP/SL (fixed/trailing/atr), один ТФ или **--all-tf** по TIMEFRAMES_DB; **run_all_tf_for_chart(year, …)** для графика в боте. **compare_phase_methods.py**: сравнение трёх методов фаз (Wyckoff / Indicators / Structure). **full_backfill.py**: полный бэкфилл за весь период Bybit. **refill_tf_d.py**: перезалив только ТФ D с биржи. **test_run_once.py**: один прогон анализа (в т.ч. торговые зоны). **test_zones.py**: тест торговых зон по БД. **trend_daily_full.py**: тренд по всей БД на ТФ D с визуализацией. **trend_backtest_report.py**: отчёт по бэктесту тренда.
- **Корень:** `main.py`, `telegram_bot.py`, `check_all.py`, `release.py`. Остальные скрипты — в **bin/** (запуск из корня: `python bin/catch_up_db.py`, `python bin/accumulate_db.py` и т.д.). Скрипты в bin/ поднимают sys.path на корень и вызывают модули из `src.app` или `src.scripts`.
- **Реализовано:** **strategies/** (заготовка), **tests/** (unit/, integration/, backtest/), **src/utils/** (validators, helpers, candle_quality, **backtest_chart** — build_phases_chart, build_trend_chart, build_candlestick_trend_chart, build_daily_trend_full_chart, **build_trade_2025_chart**: график PnL и итог по ТФ за год для Telegram; свечной график без зон трендов по умолчанию; фильтр цен 1k–150k USDT и (high-low)/open ≤ 30% для BTC), **backtest_engine** (run_backtest с TP/SL), **tp_sl** (Fixed, ATR, TrailingStop, ATRTrailing), **src/core/logging_config.py**. **Микроструктура и Order Flow:** **src/analysis/orderflow.py** — DOM (analyze_dom: стены, imbalance), Time & Sales (analyze_time_and_sales: объём за окно, скорость, всплеск), Volume Delta (compute_volume_delta), Sweeps (detect_sweeps по свечам и уровням DOM/trading_zones). **src/core/trades_ws.py** — TradesStream (WebSocket publicTrade, буфер сделок, get_recent_trades_since). Интеграция в **bot_loop**: при ORDERFLOW_ENABLED в main запускаются OrderbookStream и TradesStream, на каждом тике вызывается analyze_orderflow (стакан, сделки за окно, свечи младшего ТФ для sweep), результат в report["orderflow"] и в лог (imbalance, delta, last_sweep). При **ORDERFLOW_SAVE_TO_DB=1** метрики пишутся в таблицу **orderflow_metrics** (та же БД); чтение — get_orderflow_metrics (для бэктеста/анализа). Конфиг: ORDERFLOW_ENABLED, ORDERFLOW_WINDOW_SEC, ORDERFLOW_SAVE_TO_DB. **Сигнал по микроструктуре:** **src/analysis/microstructure_signal.py** — compute_microstructure_signal(of_result) возвращает direction (long/short/none), confidence, reason, details (score, вклады delta/imbalance/sweep). Используется как отдельный «голос» для комбинирования с мультиТФ-сигналом; тесты — tests/unit/test_microstructure_signal.py. **Песочница микроструктуры:** **src/app/microstructure_sandbox.py** — MicrostructureSandbox: виртуальная позиция и PnL по сигналу microstructure_signal (long/short/none). Цена — mid стакана. При MICROSTRUCTURE_SANDBOX_ENABLED=1 и ORDERFLOW_ENABLED=1 в main создаётся песочница, на каждом тике обновляется по of_result и mid, состояние пишется в report и в лог (позиция, realized_pnl, unrealized_pnl). **Бэктест песочницы по тикам:** **src/scripts/backtest_sandbox.py**, лаунчер **bin/backtest_sandbox.py** — replay тиков из `data/history/trades/{SYMBOL}/` (поддержка подпапок по году: 2023/, 2024/, 2025/), синтетический стакан из дельты; `--from`, `--to`, `--symbol`, `--tick-sec`, `--window-sec`; **проверка повторных прогонов:** пройденные диапазоны в `logs/sandbox_backtest_completed.json` — повторный запуск того же диапазона пропускается; `--force` для перезапуска, `--mark-done` чтобы только записать диапазон как пройденный. **Отчёт по бэктесту песочницы:** **bin/sandbox_backtest_report.py** — `--year YYYY` (реализованный PnL, комиссия, разбивка по причинам выхода); `--all` или `--years 2023,2024,2025` — сводка по годам. **Загрузка тиков:** **bin/download_history.py** — `--download --from/--to` сохраняет в папки по году `trades/{SYMBOL}/{YEAR}/`; `--list`, `--mkdir`, `--organize-by-year` — раскидать существующие CSV по папкам года.
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
- **Стакан в реальном времени:** реализовано — REST get_orderbook (снимок) и WebSocket OrderbookStream (orderbook_ws), snapshot + delta, потокобезопасный get_snapshot().
- **Микроструктура и Order Flow:** реализовано — orderflow.py (DOM, T&S, Delta, Sweeps), TradesStream (trades_ws), интеграция в bot_loop по флагу ORDERFLOW_ENABLED.
- Исполнение ордеров через Bybit API по сигналу из multi_tf.
- Риск-менеджмент: размер позиции, стоп-лосс, тейк-профит.
- Использование БД для обучения моделей (чтение из klines по symbol/timeframe/диапазону).
- При желании — поддержка нескольких пар и отдельная конфигурация стратегии.

### Управление сделкой (план)

Чтобы система **сопровождала открытую сделку** и принимала дальнейшие решения по ней:

1. **Источник позиции** — запрос к Bybit (позиция по символу) и/или своя таблица `positions` (symbol, side, size, entry_price, entry_time).
2. **На каждом тике в bot_loop** (после `analyze_multi_timeframe`): если есть открытая позиция — вызвать модуль управления сделкой.
3. **Входы модуля**: позиция (side, size, entry_price, entry_time), последние свечи по нужному ТФ, отчёт multi_tf (сигнал, narrative), состояние TP/SL (`state` из `tp_sl`).
4. **Логика выхода** (порядок проверок, как в backtest_engine): time_stop (опционально) → достижение SL → достижение TP → выход по смене сигнала (например long при short или none с достаточной уверенностью).
5. **Уровни TP/SL** — пересчитывать на каждом тике через существующие handler’ы из `src/utils/tp_sl.py` (Fixed, ATR, TrailingStop, ATRTrailing); состояние трейлинга/безубытка хранить в `state` между тиками.
6. **Итог**: один слой «trade management» решает только «держать или закрыть и по какой причине»; исполнение ордеров — отдельно (Bybit API).

---

Полная карта проекта (дерево, таблицы по назначению) — **STRUCTURE.md**.

## Куда смотреть по задачам

| Задача | Файлы / места |
|--------|----------------|
| Пара, ТФ, лимиты, порог фазы (PHASE_SCORE_MIN) | src/core/config.py, .env |
| Запросы к Bybit, бэкфилл, стакан REST (get_orderbook) | src/core/exchange.py |
| Стакан WebSocket в реальном времени (OrderbookStream) | src/core/orderbook_ws.py |
| Микроструктура и Order Flow (DOM, T&S, Delta, Sweeps) | src/analysis/orderflow.py, docs/ORDERFLOW_MICROSTRUCTURE.md |
| Сигнал по микроструктуре (long/short/none по Order Flow) | src/analysis/microstructure_signal.py, tests/unit/test_microstructure_signal.py |
| Схема БД, вставка, выборки, get_candles | src/core/database.py |
| Накопление свечей | src/scripts/accumulate_db.py |
| 6 фаз рынка | src/analysis/market_phases.py |
| Бэктест точности фаз, --min-score, --tune | src/scripts/backtest_phases.py, bin/backtest_phases.py |
| Сравнение методов фаз (Wyckoff / Indicators / PA) | src/scripts/compare_phase_methods.py, bin/compare_phase_methods.py |
| 6 фаз (эксперимент: только Вайкофф / только индикаторы / только PA) | src/analysis/phase_wyckoff.py, phase_indicators.py, phase_structure.py |
| Логика сигнала, единый score входа, тренды, режим, фильтры, качество свечей, агрегация по ТФ | src/analysis/multi_tf.py |
| Модуль тренда и режима (detect_trend, detect_regime) | src/analysis/market_trend.py |
| Проверка качества свечей (OHLCV, валидность) | src/utils/candle_quality.py |
| Цикл и лог | src/app/main.py, main.py (лаунчер) |
| Полный бэкфилл за весь период | src/scripts/full_backfill.py, bin/full_backfill.py |
| Управление через Telegram, /signal /zones /momentum /health /chart /trend_backtest /trade_2025 | src/app/telegram_bot.py, telegram_bot.py (лаунчер); TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_IDS, TELEGRAM_ALERT_* |
| Торговые зоны (уровни, перевороты ролей, confluence) | src/analysis/trading_zones.py, multi_tf.py |
| Визуализация графиков (фазы, тренд, свечной с трендами, тренд по всей БД D, бэктест по ТФ за год) | src/utils/backtest_chart.py |
| Тренд по всей БД ТФ D с визуализацией | bin/trend_daily_full.py, src/scripts/trend_daily_full.py |
| Бэктест сценария управления сделкой на одном году (сигнал + TP/SL) | bin/backtest_trade_2025.py, src/scripts/backtest_trade_2025.py |
| Отчёт по бэктесту тренда (график точности) | bin/trend_backtest_report.py, src/scripts/trend_backtest_report.py |
| Тесты тренда (юнит + точность на D) | tests/unit/test_market_trend.py, tests/backtest/test_trend_accuracy.py |
| Полное обновление БД (удаление + загрузка всех ТФ) | bin/refresh_db.py, `python bin/refresh_db.py [--yes]` |
| Перезалив ТФ D, догрузка БД до текущей даты, дозаполнение пропусков | bin/refill_tf_d.py, bin/catch_up_db.py, bin/fill_gap_db.py |
| Умные выборки по БД (актуальность, кэш, дозаполнение пропусков) | src/core/db_helper.py — ensure_fresh_then_get, get_candles_last_days, is_stale, catch_up_tf |
| Версии, теги, push в GitHub, откат | release.py (в корне) |
| Онбординг человека | ДЛЯ_КОМАНДЫ.md |
| Проверка работоспособности, выбросы цен в БД (BTC) | check_all.py (в корне), `python check_all.py [--quick] [-v]` |
| Бэктест песочницы по тикам, отчёт по годам, тики по годам | bin/backtest_sandbox.py (--from/--to, --force, --mark-done), bin/sandbox_backtest_report.py (--year, --all), bin/download_history.py (--download, --organize-by-year); logs/sandbox_backtest_completed.json |

---

## Важные договорённости

- Конфиг только из .env через config.py.
- Стакан: ORDERBOOK_LIMIT (REST, 1–500 для linear); get_orderbook в exchange.py. WebSocket: orderbook_ws.OrderbookStream, depth 1/50/200/1000 для linear.
- Порог фазы: PHASE_SCORE_MIN, PHASE_UNCLEAR_THRESHOLD, PHASE_MIN_GAP, PHASE_STABILITY_MIN, PHASE_HISTORY_SIZE. Тренд: TREND_STRENGTH_MIN, TREND_UNCLEAR_THRESHOLD, TREND_MIN_GAP, TREND_FLAT_WHEN_RANGE, TREND_MIN_GAP_DOWN, TREND_USE_PROFILES (адаптация по ТФ: short/long — lookback, min_gap, min_gap_down), TREND_STABILITY_MIN. Фильтры входа: VOLUME_MIN_RATIO, ATR_MAX_RATIO, TF_ALIGN_MIN, LEVEL_MAX_DISTANCE_PCT, REGIME_BLOCK_SURGE. Единый score входа: ENTRY_SCORE_WEIGHT_PHASE, ENTRY_SCORE_WEIGHT_TREND, ENTRY_SCORE_WEIGHT_TF_ALIGN. Качество свечей: CANDLE_QUALITY_MIN_SCORE (0 = не блокировать).
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
