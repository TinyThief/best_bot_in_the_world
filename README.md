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

**Накопление базы для обучения** (фьючерс BTC, все таймфреймы):

```bash
python accumulate_db.py
```

При первом запуске скрипт подключается к Bybit, создаёт SQLite-базу `data/klines.db` и по каждому таймфрейму из `TIMEFRAMES_DB` загружает историю (бэкфилл до `BACKFILL_MAX_CANDLES` свечей). Далее в цикле дотягивает новые свечи каждые `DB_UPDATE_INTERVAL_SEC` секунд. Остановка — **Ctrl+C**.

**Сигнальный бот** (анализ по таймфреймам):

```bash
python main.py
```

**Управление через Telegram:**

```bash
python telegram_bot.py
```

Если `python` не в PATH — выполни `d:\python3.12.9\python.exe telegram_bot.py` из папки проекта.

Нужен токен от [@BotFather](https://t.me/BotFather): создай бота, вставь токен в `.env` как `TELEGRAM_BOT_TOKEN`. Команды: `/start`, `/signal` — полный разбор и фазы по ТФ, `/status` — краткий статус одной строкой, `/db` — статистика БД, `/id` — твой user id для TELEGRAM_ALLOWED_IDS, `/help`. Под ответами — кнопки «Обновить» и переключение Сигнал/БД. Ограничение доступа: `TELEGRAM_ALLOWED_IDS=123,456` в `.env`.

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
├── src/                    # Ядро бота
│   ├── config.py           # Настройки из .env, PROJECT_ROOT
│   ├── exchange.py         # Клиент Bybit: свечи, бэкфилл
│   ├── database.py         # SQLite, таблица klines
│   ├── market_phases.py    # 6 фаз рынка
│   ├── multi_tf.py         # МультиТФ анализ, тренды, фазы, сигнал
│   ├── main.py              # Цикл опроса (логика)
│   ├── accumulate_db.py   # Накопление БД (логика)
│   ├── full_backfill.py   # Полный бэкфилл за весь период
│   ├── test_run_once.py   # Один прогон анализа (тест)
│   └── telegram_bot.py    # Управление через Telegram (команды /signal, /db и др.)
├── data/                   # SQLite-база (data/klines.db), в .gitignore
├── main.py                 # Точка входа: python main.py
├── accumulate_db.py        # Точка входа: python accumulate_db.py
├── full_backfill.py        # Точка входа: python full_backfill.py [--clear]
├── telegram_bot.py         # Точка входа: python telegram_bot.py (Telegram)
├── test_run_once.py        # Тест: python test_run_once.py
├── release.py              # Версии и push в GitHub
├── requirements.txt
├── .env.example
├── README.md
├── AGENT_CONTEXT.md        # Контекст для AI
└── ДЛЯ_КОМАНДЫ.md         # Онбординг для команды
```

## Дальнейшие шаги

- Добавить индикаторы (MA, RSI, уровни) на выбранные ТФ.
- Реализовать исполнение ордеров через Bybit API при появлении сигнала.
- Ввести риск-менеджмент: размер позиции, стоп-лосс, тейк-профит.
- Поддержка нескольких пар и отдельная конфигурация стратегии под каждую.

## Важно

- Сначала тестируй на **testnet** (`BYBIT_TESTNET=true`).
- Не выкладывай `.env` и реальные ключи в репозиторий.
