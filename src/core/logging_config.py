"""
Централизованная настройка логирования торгового бота.
Файлы в LOG_DIR с ротацией, консоль, отдельный лог сигналов.
Вызов setup_logging() в начале main/telegram_bot — один раз, идемпотентно.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_SETUP_DONE = False
_FORMAT_CONSOLE = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_FORMAT_FILE = "%(asctime)s [%(levelname)s] %(name)s | %(funcName)s:%(lineno)d | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_FORMAT_SIGNALS = "%(asctime)s | %(message)s"  # только сообщение, без уровня/модуля

# Имя логгера для компактного лога сигналов (одна строка на тик)
SIGNALS_LOGGER_NAME = "bot.signals"


def _level(name: str) -> int:
    return getattr(logging, name, logging.INFO)


def setup_logging() -> None:
    """
    Настраивает логирование: консоль + ротируемый файл в LOG_DIR, опционально signals.log.
    Идемпотентно: повторный вызов не добавляет дубликаты handlers.
    """
    global _LOG_SETUP_DONE
    if _LOG_SETUP_DONE:
        return

    from . import config

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # Убираем старые handlers на случай повторного вызова или basicConfig до этого
    for h in root.handlers[:]:
        root.removeHandler(h)

    level_console = _level(config.LOG_LEVEL)
    level_file = _level(config.LOG_LEVEL_FILE)

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level_console)
    console.setFormatter(logging.Formatter(_FORMAT_CONSOLE, datefmt=_DATE_FMT))
    root.addHandler(console)

    # Файл в LOG_DIR
    log_dir = Path(config.LOG_DIR) if not isinstance(config.LOG_DIR, Path) else config.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    main_log = log_dir / "bot.log"
    max_bytes = int(config.LOG_FILE_MAX_MB * 1024 * 1024)
    fh = RotatingFileHandler(
        main_log,
        maxBytes=max_bytes,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(level_file)
    fh.setFormatter(logging.Formatter(_FORMAT_FILE, datefmt=_DATE_FMT))
    root.addHandler(fh)

    # Отдельный лог сигналов — компактные строки "время | direction | reason | phase | ..."
    if config.LOG_SIGNALS_FILE:
        sig_log = log_dir / "signals.log"
        sig_handler = RotatingFileHandler(
            sig_log,
            maxBytes=max_bytes,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        sig_handler.setLevel(logging.INFO)
        sig_handler.setFormatter(logging.Formatter(_FORMAT_SIGNALS, datefmt=_DATE_FMT))
        sig_logger = logging.getLogger(SIGNALS_LOGGER_NAME)
        sig_logger.setLevel(logging.INFO)
        sig_logger.propagate = False
        sig_logger.addHandler(sig_handler)

    _LOG_SETUP_DONE = True
    logging.getLogger("bot").info(
        "Логирование настроено: dir=%s, console=%s, file=%s, signals=%s",
        log_dir,
        logging.getLevelName(level_console),
        logging.getLevelName(level_file),
        config.LOG_SIGNALS_FILE,
    )


def get_signals_logger() -> logging.Logger:
    """Логгер для записи одной строки на сигнал (в signals.log при LOG_SIGNALS_FILE=1)."""
    return logging.getLogger(SIGNALS_LOGGER_NAME)
