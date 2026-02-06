# Структура проекта — всё по полочкам

Краткая карта: что где лежит и за что отвечает.

---

## Дерево (упрощённо)

```
best_bot_in_the_world/
├── main.py              # Запуск сигнального бота (цикл + опционально Telegram)
├── telegram_bot.py      # Запуск только Telegram-бота
│
├── [Проверки и релизы]
├── check_all.py         # Проверка окружения и компонентов
├── release.py           # Версии и выгрузка в GitHub
│
├── bin/                 # Скрипты (запуск из корня: python bin/...)
│   ├── catch_up_db.py   # Догрузка БД до текущей даты
│   ├── fill_gap_db.py   # Дозаполнение пропусков в БД по всем ТФ
│   ├── refresh_db.py    # Полное обновление: удалить БД и загрузить заново
│   ├── refill_tf_d.py   # Перезалив только дневного ТФ (D)
│   ├── accumulate_db.py # Накопление БД в цикле (бэкфилл + периодическое обновление)
│   ├── full_backfill.py # Полный бэкфилл без удаления файла (--clear, --extend)
│   ├── backtest_phases.py   # Бэктест точности фаз по БД
│   ├── backtest_trend.py   # Бэктест точности модуля тренда
│   ├── backtest_trade_2025.py  # Бэктест сценария управления сделкой за год (один ТФ или --all-tf)
│   ├── compare_phase_methods.py  # Сравнение трёх методов фаз (Wyckoff / Indicators / PA)
│   ├── test_run_once.py    # Один прогон мультиТФ-анализа
│   ├── test_zones.py       # Тест торговых зон
│   ├── trend_daily_full.py # Тренд по всей БД ТФ D с визуализацией
│   ├── trend_backtest_report.py  # Отчёт по бэктесту тренда
│   ├── backtest_sandbox.py # Бэктест песочницы по тикам (--from/--to, --force)
│   ├── sandbox_backtest_report.py  # Отчёт по песочнице (--year, --db, --run-id)
│   ├── download_history.py # Загрузка тиков Bybit для бэктеста песочницы
│   ├── orderbook_ws_demo.py # Демо стакана WebSocket
│   ├── trades_ws_demo.py   # Демо потока сделок
│   └── README.md
│
├── [Конфиг и зависимости]
├── .env.example         # Шаблон .env (копируй в .env)
├── .gitignore
├── requirements.txt
│
├── [Документация]
├── README.md            # Установка, настройка, запуск
├── CHANGELOG.md         # История изменений
├── AGENT_CONTEXT.md     # Контекст для AI (состояние проекта, куда смотреть)
├── ДЛЯ_КОМАНДЫ.md       # Онбординг: структура, файлы, .env
├── STRUCTURE.md         # Этот файл — карта проекта
├── AUDIT_VISUALIZATION.md  # Аудит визуализации графика
├── docs/                # Дизайн: trading_zones, parallel multi_tf, telegram upgrade, Wyckoff
├── .cursorrules         # Правила для Cursor (корень)
├── .cursor/rules/       # Правила Cursor (trading-bot.mdc)
│
├── src/                 # Исходный код
│   ├── core/            # Инфраструктура
│   │   ├── config.py    # Конфиг из .env
│   │   ├── database.py  # SQLite: klines, orderflow_metrics, sandbox_runs/sandbox_trades/sandbox_skips (run_id)
│   │   ├── db_helper.py # Умные выборки, кэш, дозаполнение пропусков
│   │   ├── exchange.py  # Bybit API (свечи, фильтр OHLC)
│   │   └── logging_config.py
│   ├── analysis/        # Аналитика
│   │   ├── market_phases.py   # Фазы рынка (Вайкофф + индикаторы)
│   │   ├── market_trend.py    # Тренд, режим рынка, импульс
│   │   ├── trading_zones.py   # Торговые зоны (уровни, перевороты ролей, confluence)
│   │   ├── multi_tf.py        # МультиТФ-анализ (параллельно по ТФ), сигнал long/short/none
│   │   └── phase_*.py         # Экспериментальные модули фаз
│   ├── app/             # Приложения
│   │   ├── main.py      # Цикл бота, db_sync, опционально Telegram
│   │   ├── bot_loop.py  # Один тик: обновление БД + анализ + лог
│   │   ├── db_sync.py   # Подготовка БД, refresh_if_due
│   │   ├── microstructure_sandbox.py  # Песочница микроструктуры (run_id, запись в БД и CSV)
│   │   └── telegram_bot.py    # Команды /signal, /zones, /momentum, /health, /chart, /trend_backtest, /trade_2025; inline Сигнал|Зоны|Импульс; алерт при смене сигнала
│   ├── scripts/         # Скрипты (логика; точки входа — bin/)
│   │   ├── accumulate_db.py
│   │   ├── full_backfill.py
│   │   ├── refill_tf_d.py
│   │   ├── backtest_phases.py, backtest_trend.py, backtest_trade_2025.py
│   │   ├── compare_phase_methods.py
│   │   ├── trend_daily_full.py, trend_backtest_report.py
│   │   ├── test_run_once.py, test_zones.py
│   │   └── README.md          # Список команд bin/
│   └── utils/           # Утилиты
│       ├── backtest_chart.py  # Графики (фазы, тренд, свечной /chart, бэктест по ТФ за год /trade_2025)
│       ├── backtest_engine.py # Движок бэктеста с TP/SL (run_backtest)
│       ├── tp_sl.py           # TP/SL: Fixed, ATR, TrailingStop, ATRTrailing
│       ├── candle_quality.py
│       ├── helpers.py
│       └── validators.py
│
├── strategies/          # Заготовка под стратегии (пока пусто)
├── tests/               # unit/, integration/, backtest/
├── data/                # klines.db (klines + orderflow_metrics, в .gitignore)
└── logs/                # bot.log, signals.log (в .gitignore)
```

---

## По полочкам

### 1. Запуск бота

| Действие | Файл | Команда |
|----------|------|---------|
| Сигнальный бот (цикл; при наличии токена — и Telegram) | `main.py` | `python main.py` |
| Только Telegram-бот | `telegram_bot.py` | `python telegram_bot.py` |

Вся логика цикла и анализа — в `src/app/main.py`, `src/app/bot_loop.py`. Лаунчеры в корне только поднимают `sys.path` и вызывают код из `src`.

---

### 2. Работа с БД

| Действие | Файл | Команда |
|----------|------|---------|
| Догрузить БД до «сейчас» (все ТФ) | `bin/catch_up_db.py` | `python bin/catch_up_db.py` |
| Дозаполнить пропуски в БД по всем ТФ | `bin/fill_gap_db.py` | `python bin/fill_gap_db.py` |
| Полное обновление: удалить БД и загрузить заново | `bin/refresh_db.py` | `python bin/refresh_db.py [--yes]` |
| Перезалить только ТФ D | `bin/refill_tf_d.py` | `python bin/refill_tf_d.py` |
| Накопление в цикле (бэкфилл + обновление) | `bin/accumulate_db.py` | `python bin/accumulate_db.py` |
| Полный бэкфилл (без удаления файла) | `bin/full_backfill.py` | `python bin/full_backfill.py [--clear] [--extend]` |

Логика — в `src/scripts/accumulate_db.py`, `src/scripts/full_backfill.py`, `src/scripts/refill_tf_d.py`; чтение/кэш/дозаполнение — в `src/core/db_helper.py`.

---

### 3. Бэктесты и сравнения

| Действие | Файл | Команда |
|----------|------|---------|
| Бэктест точности фаз | `bin/backtest_phases.py` | `python bin/backtest_phases.py [--tf 60] [--bars N] [--tune]` |
| Бэктест точности тренда | `bin/backtest_trend.py` | `python bin/backtest_trend.py` |
| Бэктест сценария управления сделкой за год (сигнал + TP/SL) | `bin/backtest_trade_2025.py` | `python bin/backtest_trade_2025.py [--year 2025] [--tf 60]` или `--all-tf` |
| Бэктест песочницы по тикам | `bin/backtest_sandbox.py` | `python bin/backtest_sandbox.py --from YYYY-MM-DD --to YYYY-MM-DD [--force]` |
| Отчёт по песочнице (CSV или БД) | `bin/sandbox_backtest_report.py` | `python bin/sandbox_backtest_report.py [--year 2025]` или `--db [--run-id ID]` |
| Сравнение методов фаз (Wyckoff / Indicators / PA) | `bin/compare_phase_methods.py` | `python bin/compare_phase_methods.py` |
| Один прогон анализа (без цикла) | `bin/test_run_once.py` | `python bin/test_run_once.py` |

Логика — в `src/scripts/backtest_phases.py`, `backtest_trend.py`, `backtest_trade_2025.py`, `backtest_sandbox.py`, `sandbox_backtest_report.py`, `compare_phase_methods.py`, `test_run_once.py`.

---

### 4. Проверки и релизы

| Действие | Файл | Команда |
|----------|------|---------|
| Проверка окружения и компонентов | `check_all.py` | `python check_all.py [--quick] [-v]` |
| Создать версию и выгрузить в GitHub | `release.py` | `python release.py 2.6.0` |

---

### 5. Документация

| Файл | Назначение |
|------|------------|
| **README.md** | Установка, настройка, запуск, команды |
| **CHANGELOG.md** | История изменений по версиям |
| **AGENT_CONTEXT.md** | Контекст для AI: что сделано, куда смотреть |
| **ДЛЯ_КОМАНДЫ.md** | Онбординг: структура, файлы, .env, запуск |
| **STRUCTURE.md** | Карта проекта (этот файл) |
| **AUDIT_VISUALIZATION.md** | Аудит визуализации графика и фильтров |

---

### 6. Исходный код (src)

| Пакет | Назначение |
|-------|------------|
| **src/core** | Конфиг, БД, биржа, db_helper, логирование |
| **src/analysis** | Фазы рынка, тренд/режим/импульс, торговые зоны, мультиТФ-анализ (параллельно по ТФ) и сигнал |
| **src/app** | Цикл бота, синхронизация БД, Telegram-бот |
| **src/scripts** | Накопление БД, бэкфилл, бэктесты, сравнения (логика) |
| **src/utils** | Графики, качество свечей, хелперы, валидаторы |

Импорты между пакетами — относительные (`from ..core import config`). Скрипты в `bin/` запускаются из корня: `python bin/script.py`; они добавляют корень проекта в `sys.path` и вызывают `src.app.*` или `src.scripts.*`.

---

## Где что искать

| Нужно изменить… | Смотреть |
|-----------------|----------|
| Пара, ТФ, пороги, .env | `src/core/config.py`, `.env` |
| Запросы к Bybit, фильтр цен | `src/core/exchange.py` |
| Схема БД, вставка/выборка | `src/core/database.py` |
| Умные выборки, кэш, дозаполнение пропусков | `src/core/db_helper.py` |
| Фазы рынка | `src/analysis/market_phases.py` |
| Тренд и режим рынка | `src/analysis/market_trend.py` |
| Сигнал long/short/none, мультиТФ | `src/analysis/multi_tf.py` |
| Цикл бота, один тик | `src/app/main.py`, `src/app/bot_loop.py` |
| Подготовка БД, обновление по таймеру | `src/app/db_sync.py` |
| Команды Telegram, /chart, /trade_2025 | `src/app/telegram_bot.py` |
| Накопление БД, дозаполнение пропусков | `src/scripts/accumulate_db.py` |
| Бэктест по ТФ за год (run_all_tf_for_chart) | `src/scripts/backtest_trade_2025.py` |
| Графики (фазы, тренд, свечной, бэктест по ТФ за год) | `src/utils/backtest_chart.py` |
| Движок бэктеста с TP/SL | `src/utils/backtest_engine.py`, `src/utils/tp_sl.py` |

После изменений имеет смысл запускать `python check_all.py` (при необходимости с `--quick` или `-v`).
