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

    orderbook_stream = None
    trades_stream = None
    microstructure_sandbox = None
    if getattr(config, "ORDERFLOW_ENABLED", False):
        try:
            from ..core.orderbook_ws import OrderbookStream
            from ..core.trades_ws import TradesStream
            orderbook_stream = OrderbookStream()
            trades_stream = TradesStream()
            orderbook_stream.start()
            trades_stream.start()
            logger.info("Order Flow включён: стакан и поток сделок запущены")
            if getattr(config, "MICROSTRUCTURE_SANDBOX_ENABLED", False):
                from .microstructure_sandbox import MicrostructureSandbox
                initial_usd = float(getattr(config, "SANDBOX_INITIAL_BALANCE", 100) or 100)
                microstructure_sandbox = MicrostructureSandbox(initial_balance=initial_usd)
                logger.info("Песочница микроструктуры включена: $%.0f виртуальный баланс", initial_usd)
        except Exception as e:
            logger.warning("Order Flow не запущен: %s", e)

    logger.info(
        "Старт бота | пара=%s | таймфреймы=%s | интервал опроса=%s с",
        config.SYMBOL,
        config.TIMEFRAMES,
        config.POLL_INTERVAL_SEC,
    )

    # 0 — чтобы первый тик сразу обновил БД (догрузка до текущей даты), дальше по таймеру
    last_db_ts = 0.0
    try:
        while True:
            last_db_ts = run_one_tick(
                db_conn,
                last_db_ts,
                orderbook_stream=orderbook_stream,
                trades_stream=trades_stream,
                microstructure_sandbox=microstructure_sandbox,
            )
            time.sleep(config.POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        # Итог песочницы микроструктуры до остановки потоков (нужен стакан для mid)
        if microstructure_sandbox is not None and orderbook_stream is not None:
            try:
                from .microstructure_sandbox import _mid_from_snapshot
                snap = orderbook_stream.get_snapshot()
                mid = _mid_from_snapshot(snap)
                if mid is not None:
                    state = microstructure_sandbox.get_state()
                    unrealized = microstructure_sandbox.unrealized_pnl(mid)
                    equity = microstructure_sandbox.initial_balance + microstructure_sandbox.total_realized_pnl + unrealized
                    logger.info(
                        "Итог песочницы микроструктуры: позиция=%s | старт=$%.0f | реализовано=$%.2f | нереализовано=$%.2f | эквити=$%.2f",
                        state.get("position_side", "—"),
                        microstructure_sandbox.initial_balance,
                        microstructure_sandbox.total_realized_pnl,
                        unrealized,
                        equity,
                    )
                    # Запись в файл для просмотра результатов
                    from pathlib import Path
                    from datetime import datetime
                    log_dir = getattr(config, "LOG_DIR", None) or Path(__file__).resolve().parents[2] / "logs"
                    if isinstance(log_dir, str):
                        log_dir = Path(log_dir)
                    log_dir.mkdir(parents=True, exist_ok=True)
                    result_path = log_dir / "sandbox_result.txt"
                    with open(result_path, "a", encoding="utf-8") as f:
                        f.write(
                            f"[{datetime.utcnow().isoformat()}Z] "
                            f"позиция={state.get('position_side')} | старт=${microstructure_sandbox.initial_balance:.0f} | "
                            f"реализовано=${microstructure_sandbox.total_realized_pnl:.2f} | нереализовано=${unrealized:.2f} | эквити=${equity:.2f}\n"
                        )
                    logger.info("Результат песочницы записан в %s", result_path)
            except Exception as e:
                logger.debug("Итог песочницы не записан: %s", e)
        if orderbook_stream is not None:
            try:
                orderbook_stream.stop()
            except Exception:
                pass
        if trades_stream is not None:
            try:
                trades_stream.stop()
            except Exception:
                pass
        close(db_conn)


if __name__ == "__main__":
    main()
