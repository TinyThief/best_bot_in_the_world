# Мультитаймфреймовый торговый бот для Bybit

Бот анализирует несколько таймфреймов по выбранной паре на Bybit и формирует направление (long/short/none) на основе тренда старшего таймфрейма.

## Установка

```bash
cd d:\python3.12.9\MyPythonProjects\best_bot_in_the_world
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Если команда `python` не находится (Windows), используй полный путь к интерпретатору, например:
`d:\python3.12.9\python.exe -m venv .venv` и т.д.

## Настройка

1. Скопируй `.env.example` в `.env`:

   ```bash
   copy .env.example .env
   ```

2. В `.env` укажи:
   - **BYBIT_API_KEY** / **BYBIT_API_SECRET** — для торговли (для одного чтения свечей можно оставить пустыми).
   - **BYBIT_TESTNET** — `true` для тестнета, `false` для боевой среды.
   - **BYBIT_CATEGORY** — `linear` (USDT‑фьючерсы), `inverse` или `spot`.
   - **SYMBOL** — пара, например `BTCUSDT`.
   - **TIMEFRAMES** — таймфреймы через запятую: `15,60,240` или `1,5,15,60,D`.
   - **POLL_INTERVAL_SEC** — как часто пересчитывать сигнал (в секундах).

## Запуск

**Одноразовая догрузка БД до текущей даты** (если БД давно не обновлялась):

```bash
python catch_up_db.py
```

Скрипт догружает пропущенные свечи от последней в БД до «сейчас» по всем ТФ из `TIMEFRAMES_DB` и выводит дату последней свечи (ТФ D и 60). Для постоянного обновления используй `main.py` или `accumulate_db.py`.

**Полное обновление БД** — удалить файл БД и заново загрузить все таймфреймы из `TIMEFRAMES_DB` с биржи (актуальные данные, один масштаб):

```bash
python refresh_db.py
```

Скрипт запросит подтверждение, затем удалит `data/klines.db` и загрузит историю по каждому ТФ из `.env` (TIMEFRAMES_DB). Перед запуском останови бота (`main.py`, `telegram_bot.py`). Без подтверждения: `python refresh_db.py --yes`. Если `python` не в PATH: `py -3 refresh_db.py` или полный путь к интерпретатору.

**Перезалив только дневного ТФ (D)** — если в БД по ТФ D попали некорректные цены (например миллионы вместо десятков тысяч):

```bash
python refill_tf_d.py
```

Скрипт удаляет все свечи по выбранной паре и ТФ D, затем загружает историю заново с Bybit (с фильтром нереалистичных цен).

**Накопление базы для обучения** (фьючерс BTC, все таймфреймы):

```bash
python accumulate_db.py
```

При первом запуске скрипт подключается к Bybit, создаёт SQLite-базу `data/klines.db` и по каждому таймфрейму из `TIMEFRAMES_DB` загружает историю (бэкфилл до `BACKFILL_MAX_CANDLES` свечей). Далее в цикле дотягивает новые свечи каждые `DB_UPDATE_INTERVAL_SEC` секунд. Остановка — **Ctrl+C**.

**Сигнальный бот** (анализ по таймфреймам):

```bash
python main.py
```

При старте БД сразу догружается до текущей даты (первый тик), далее обновляется каждые `DB_UPDATE_INTERVAL_SEC` секунд. При заданном в `.env` токене `TELEGRAM_BOT_TOKEN` Telegram-бот запускается из `main.py` в отдельном потоке (общее соединение с БД). Для работы только сигнального бота оставь `TELEGRAM_BOT_TOKEN` пустым.

**Управление через Telegram** (отдельный процесс, если не используешь запуск из main):

```bash
python telegram_bot.py
```

Если `python` не в PATH — выполни `d:\python3.12.9\python.exe telegram_bot.py` из папки проекта.

Нужен токен от [@BotFather](https://t.me/BotFather): создай бота, вставь токен в `.env` как `TELEGRAM_BOT_TOKEN`. Команды: `/start`, `/signal` — полный разбор и фазы по ТФ, `/status` — краткий статус одной строкой, `/db` — статистика БД, `/backtest_phases` — график бэктеста фаз, `/chart` — свечной график с трендами Вверх/Вниз/Флэт (из БД, ТФ D), `/id` — твой user id для TELEGRAM_ALLOWED_IDS, `/help`. Под ответами — кнопки «Обновить» и переключение Сигнал/БД. Ограничение доступа: `TELEGRAM_ALLOWED_IDS=123,456` в `.env`.

## База данных для обучения

- Файл по умолчанию: `data/klines.db` (путь задаётся в `DB_PATH`).
- Таблица `klines`: `symbol`, `timeframe`, `start_time`, `open`, `high`, `low`, `close`, `volume`.
- Один запуск `accumulate_db.py`: первый проход — бэкфилл по всем ТФ из `TIMEFRAMES_DB`, затем периодическое обновление. Ключи API для чтения свечей не нужны.

В `.env` для накопления можно задать:

- **DB_PATH** — путь к файлу БД.
- **TIMEFRAMES_DB** — таймфреймы через запятую, например `1,3,5,15,30,60,120,240,360,720,D,W,M`.
- **BACKFILL_MAX_CANDLES** — максимум свечей вглубь при первом бэкфилле на один ТФ (по умолчанию 50000).
- **DB_UPDATE_INTERVAL_SEC** — интервал обновления в секундах (по умолчанию 60).

## Версии и выгрузка в GitHub

Что изменилось между версиями — в **[CHANGELOG.md](CHANGELOG.md)**.

Скрипт **release.py** создаёт тег версии, при необходимости коммитит изменения и пушит ветку и теги в `origin`. Так можно откатиться на любую версию.

**Первый раз:** инициализация репозитория и привязка к GitHub:

```bash
git init
git remote add origin https://github.com/<user>/<repo>.git
git add -A
git commit -m "Initial"
```

**Создать версию и выгрузить:**

```bash
python release.py 1.0.0
```

Скрипт закоммитит незакоммиченные изменения с сообщением «Release v1.0.0», создаст тег `v1.0.0` и выполнит `git push origin <текущая_ветка>` и `git push origin v1.0.0`.

**Только тег** (без нового коммита): `python release.py 1.0.1 --tag-only`  
**Локально без push:** `python release.py 1.0.0 --no-push`

**Откат на прошлую версию:**

```bash
git checkout v1.0.0
```

Вернуться на актуальную ветку: `git checkout main` (или имя вашей ветки).

**Список тегов:** `git tag -l`

---

## Структура проекта

```
best_bot_in_the_world/
├── src/
│   ├── core/               # config, database, exchange, logging_config
│   ├── analysis/           # market_phases (6 фаз, Вайкофф + индикаторы), market_trend (тренд, режим рынка), multi_tf
│   │                        # phase_wyckoff, phase_indicators, phase_structure — для сравнения
│   ├── app/                # main, bot_loop, db_sync, telegram_bot
│   ├── scripts/            # accumulate_db, backtest_phases, compare_phase_methods, full_backfill, test_run_once
│   └── utils/              # validators, helpers, candle_quality
├── strategies/             # Заготовка под стратегии
├── tests/                  # unit/, integration/, backtest/
├── data/                   # SQLite (data/klines.db), в .gitignore
├── logs/                   # bot.log, signals.log, в .gitignore
├── main.py                 # Точка входа: python main.py
├── telegram_bot.py        # python telegram_bot.py
├── accumulate_db.py        # python accumulate_db.py
├── backtest_phases.py      # Бэктест фаз: python backtest_phases.py [--tf 60] [--tune]
├── backtest_trend.py       # Бэктест тренда: python backtest_trend.py [--tf 60]
├── compare_phase_methods.py # Сравнение методов фаз: python compare_phase_methods.py
├── full_backfill.py        # python full_backfill.py [--clear] [--extend]
├── refresh_db.py           # Удалить БД и загрузить все ТФ заново: python refresh_db.py [--yes]
├── test_run_once.py        # python test_run_once.py
├── check_all.py            # Проверка окружения: python check_all.py [--quick] [-v]
├── release.py              # Версии и push: python release.py 1.0.0
├── requirements.txt, .env.example
├── README.md, AGENT_CONTEXT.md, ДЛЯ_КОМАНДЫ.md, CHANGELOG.md
└── .cursorrules, .cursor/rules/
```

## Дальнейшие шаги

- Фазы, тренд, режим рынка, фильтры входа, единый score входа (фаза + тренд + ТФ) и проверка качества свечей уже реализованы. Дальше — тонкая настройка порогов и стратегий.
- Реализовать исполнение ордеров через Bybit API при появлении сигнала.
- Ввести риск-менеджмент: размер позиции, стоп-лосс, тейк-профит.
- Поддержка нескольких пар и отдельная конфигурация стратегии под каждую.

## Важно

- Сначала тестируй на **testnet** (`BYBIT_TESTNET=true`).
- Не выкладывай `.env` и реальные ключи в репозиторий.
