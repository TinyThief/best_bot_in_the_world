"""
Точка входа мультитаймфреймового торгового бота для Bybit.
Только цикл и запуск: конфиг, подготовка БД, вызов bot_loop.run_one_tick, пауза, завершение.
Telegram-бот (если задан TELEGRAM_BOT_TOKEN) запускается в отдельном потоке и использует то же соединение с БД.
"""
import asyncio
import logging
import threading
import time

from ..core import config
from ..core.config import validate_config
from ..core.logging_config import setup_logging
from .bot_loop import run_one_tick
from .db_sync import close, open_and_prepare

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    errs = validate_config()
    if errs:
        for e in errs:
            logger.warning("Конфиг: %s", e)
        logger.info("Запуск в режиме только чтения (без сделок)")

    db_conn = open_and_prepare()
    if db_conn is not None:
        logger.info(
            "БД будет обновляться каждые %s с",
            config.DB_UPDATE_INTERVAL_SEC,
        )
    else:
        logger.info("TIMEFRAMES_DB пуст — обновление БД отключено")

    telegram_thread = None
    if config.TELEGRAM_BOT_TOKEN:
        from .telegram_bot import run_bot

        def _run_telegram_in_thread(db_conn):
            # В новом потоке нет event loop; APScheduler/python-telegram-bot вызывают get_event_loop().
            asyncio.set_event_loop(asyncio.new_event_loop())
            run_bot(db_conn=db_conn)

        telegram_thread = threading.Thread(
            target=_run_telegram_in_thread,
            kwargs={"db_conn": db_conn},
            daemon=True,
        )
        telegram_thread.start()
        logger.info("Telegram-бот запущен от основного бота (общее соединение с БД)")

    logger.info(
        "Старт бота | пара=%s | таймфреймы=%s | интервал опроса=%s с",
        config.SYMBOL,
        config.TIMEFRAMES,
        config.POLL_INTERVAL_SEC,
    )

    last_db_ts = time.time()
    try:
        while True:
            last_db_ts = run_one_tick(db_conn, last_db_ts)
            time.sleep(config.POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        close(db_conn)


if __name__ == "__main__":
    main()
