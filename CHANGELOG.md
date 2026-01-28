# История изменений

Все значимые изменения в проекте описаны в этом файле.

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

[2.0.0]: https://github.com/TinyThief/best_bot_in_the_world/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/TinyThief/best_bot_in_the_world/releases/tag/v1.0.0
