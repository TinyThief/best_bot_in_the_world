"""
Накопление базы данных для обучения: фьючерс BTC на всех таймфреймах.
Подключается к Bybit, при первом запуске делает бэкфилл истории, затем
периодически дотягивает новые свечи по каждому ТФ.
Запуск: python accumulate_db.py
Остановка: Ctrl+C
"""
import logging
import time

import config
from database import (
    get_connection,
    get_db_path,
    get_latest_start_time,
    init_db,
    insert_candles,
)
from exchange import fetch_klines_backfill, get_klines

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_backfill_for_timeframe(
    cursor,
    symbol: str,
    timeframe: str,
) -> int:
    """
    Если по этому ТФ в БД ещё нет данных — загружает историю вглубь (бэкфилл).
    Возвращает количество вставленных свечей.
    """
    latest = get_latest_start_time(cursor, symbol, timeframe)
    if latest is not None:
        return 0  # уже есть данные, бэкфилл не нужен

    logger.info("Бэкфилл ТФ %s для %s...", timeframe, symbol)
    end_ms = int(time.time() * 1000)
    candles = fetch_klines_backfill(
        symbol=symbol,
        interval=timeframe,
        end_ms=end_ms,
        max_candles=config.BACKFILL_MAX_CANDLES,
        limit_per_request=1000,
        category=config.BYBIT_CATEGORY,
    )
    n = insert_candles(cursor, symbol, timeframe, candles)
    logger.info("  ТФ %s: загружено %s свечей, вставлено %s", timeframe, len(candles), n)
    return n


def run_update_for_timeframe(
    cursor,
    symbol: str,
    timeframe: str,
    limit: int = 500,
) -> int:
    """
    Дотягивает последние свечи с биржи и добавляет в БД (только новые).
    Возвращает количество вставленных свечей.
    """
    candles = get_klines(
        symbol=symbol,
        interval=timeframe,
        category=config.BYBIT_CATEGORY,
        limit=limit,
    )
    n = insert_candles(cursor, symbol, timeframe, candles)
    return n


def run_once(conn, backfill: bool = True) -> dict[str, int]:
    """
    Один проход: по каждому ТФ из TIMEFRAMES_DB делается бэкфилл (если нужен)
    и дополнение новыми свечами. Возвращает счётчики по ТФ: { "15": 12, "60": 3, ... }.
    """
    cursor = conn.cursor()
    symbol = config.SYMBOL
    totals: dict[str, int] = {}

    for tf in config.TIMEFRAMES_DB:
        try:
            if backfill:
                run_backfill_for_timeframe(cursor, symbol, tf)
            added = run_update_for_timeframe(cursor, symbol, tf)
            totals[tf] = added
        except Exception as e:
            logger.exception("Ошибка по ТФ %s: %s", tf, e)
            totals[tf] = 0

    conn.commit()
    return totals


def main() -> None:
    if not config.TIMEFRAMES_DB:
        logger.error("В конфиге не заданы таймфреймы для БД (TIMEFRAMES_DB). Пример: 1,3,5,15,30,60,120,240,360,720,D,W,M")
        return
    symbol = config.SYMBOL
    logger.info(
        "Накопление БД для обучения | пара=%s (фьючерс %s) | таймфреймы=%s | файл=%s",
        symbol,
        config.BYBIT_CATEGORY,
        config.TIMEFRAMES_DB,
        get_db_path(),
    )

    init_db()
    conn = get_connection()

    # Первый проход — с бэкфиллом
    logger.info("Первый проход (бэкфилл + актуализация)...")
    run_once(conn, backfill=True)

    # Далее только подтягиваем новые свечи
    logger.info(
        "Режим накопления: обновление каждые %s с. Остановка: Ctrl+C.",
        config.DB_UPDATE_INTERVAL_SEC,
    )
    try:
        while True:
            time.sleep(config.DB_UPDATE_INTERVAL_SEC)
            totals = run_once(conn, backfill=False)
            if any(totals.values()):
                logger.info("Добавлено по ТФ: %s", totals)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
