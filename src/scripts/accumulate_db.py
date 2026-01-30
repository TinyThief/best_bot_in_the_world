"""Накопление БД для обучения: бэкфилл + догрузка пропусков + периодическое обновление по всем ТФ."""
import logging
import time

from ..core import config
from ..core.logging_config import setup_logging
from ..core.database import (
    get_connection,
    get_db_path,
    get_latest_start_time,
    get_oldest_start_time,
    init_db,
    insert_candles,
)
from ..core.exchange import fetch_klines_backfill, get_klines

logger = logging.getLogger(__name__)

# Интервал таймфрейма в миллисекундах (для догрузки пропусков)
_TF_MS: dict[str, int] = {
    "1": 60_000,
    "3": 180_000,
    "5": 300_000,
    "15": 900_000,
    "30": 1_800_000,
    "60": 3_600_000,
    "120": 7_200_000,
    "240": 14_400_000,
    "360": 21_600_000,
    "720": 43_200_000,
    "D": 86_400_000,
    "W": 604_800_000,
    "M": 30 * 86_400_000,
}


def run_extend_backward_one_chunk(cursor, symbol: str, timeframe: str, category: str, max_candles: int) -> int:
    """Подгружает вглубь истории один чанк свечей до текущей самой старой по этому ТФ. Возвращает число вставленных."""
    oldest = get_oldest_start_time(cursor, symbol, timeframe)
    if oldest is None:
        return 0
    end_ms = oldest - 1
    candles = fetch_klines_backfill(
        symbol=symbol,
        interval=timeframe,
        end_ms=end_ms,
        max_candles=max_candles,
        limit_per_request=1000,
        category=category,
    )
    return insert_candles(cursor, symbol, timeframe, candles)


def run_extend_until_done(conn, symbol: str | None = None) -> dict[str, int]:
    """
    По каждому ТФ из TIMEFRAMES_DB углубляет историю вглубь, пока подгружаются новые свечи.
    Возвращает суммарно по каждому ТФ число добавленных свечей за этот запуск.
    """
    symbol = symbol or config.SYMBOL
    category = config.BYBIT_CATEGORY
    max_candles = config.BACKFILL_MAX_CANDLES
    cursor = conn.cursor()
    totals: dict[str, int] = {tf: 0 for tf in config.TIMEFRAMES_DB}
    for tf in config.TIMEFRAMES_DB:
        try:
            while True:
                n = run_extend_backward_one_chunk(cursor, symbol, tf, category, max_candles)
                conn.commit()
                if n == 0:
                    break
                totals[tf] += n
                logger.info("  ТФ %s: углублено на %s свечей", tf, n)
        except Exception as e:
            logger.exception("Углубление ТФ %s: %s", tf, e)
    return totals


def run_backfill_for_timeframe(cursor, symbol: str, timeframe: str) -> int:
    if get_latest_start_time(cursor, symbol, timeframe) is not None:
        return 0
    logger.info("Бэкфилл ТФ %s для %s...", timeframe, symbol)
    candles = fetch_klines_backfill(symbol=symbol, interval=timeframe, end_ms=int(time.time() * 1000), max_candles=config.BACKFILL_MAX_CANDLES, limit_per_request=1000, category=config.BYBIT_CATEGORY)
    n = insert_candles(cursor, symbol, timeframe, candles)
    logger.info("  ТФ %s: загружено %s, вставлено %s", timeframe, len(candles), n)
    return n


def run_update_for_timeframe(cursor, symbol: str, timeframe: str, limit: int = 500) -> int:
    candles = get_klines(symbol=symbol, interval=timeframe, category=config.BYBIT_CATEGORY, limit=limit)
    return insert_candles(cursor, symbol, timeframe, candles)


def run_fill_gap_for_timeframe(cursor, symbol: str, timeframe: str) -> int:
    """
    Дозаполняет пропуски в БД между самой старой и самой новой свечой по этому ТФ.
    Вызывать после catch_up, если на графике виден разрыв (например, часть года пропала).
    Возвращает число вставленных свечей.
    """
    oldest_ms = get_oldest_start_time(cursor, symbol, timeframe)
    latest_ms = get_latest_start_time(cursor, symbol, timeframe)
    if oldest_ms is None or latest_ms is None or latest_ms <= oldest_ms:
        return 0
    interval_ms = _TF_MS.get(str(timeframe).strip().upper())
    if not interval_ms:
        return 0
    total_inserted = 0
    chunk = 1000
    start_ms = oldest_ms + interval_ms
    end_ms = latest_ms - interval_ms
    if start_ms >= end_ms:
        return 0
    while start_ms < end_ms:
        candles = get_klines(
            symbol=symbol,
            interval=timeframe,
            category=config.BYBIT_CATEGORY,
            limit=chunk,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if not candles:
            break
        n = insert_candles(cursor, symbol, timeframe, candles)
        total_inserted += n
        if len(candles) < chunk:
            break
        start_ms = candles[-1]["start_time"] + interval_ms
    return total_inserted


def run_catch_up_for_timeframe(cursor, symbol: str, timeframe: str) -> int:
    """Догружает пропущенные свечи с момента последней в БД до текущего времени."""
    latest_ms = get_latest_start_time(cursor, symbol, timeframe)
    if latest_ms is None:
        return 0
    interval_ms = _TF_MS.get(str(timeframe).strip().upper())
    if not interval_ms:
        return 0
    end_ms = int(time.time() * 1000)
    start_ms = latest_ms + interval_ms
    if start_ms >= end_ms:
        return 0
    total_inserted = 0
    chunk = 1000
    while start_ms < end_ms:
        candles = get_klines(
            symbol=symbol,
            interval=timeframe,
            category=config.BYBIT_CATEGORY,
            limit=chunk,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if not candles:
            break
        n = insert_candles(cursor, symbol, timeframe, candles)
        total_inserted += n
        if len(candles) < chunk:
            break
        start_ms = candles[-1]["start_time"] + interval_ms
    return total_inserted


def run_catch_up(conn, symbol: str | None = None) -> dict[str, int]:
    """По всем ТФ из TIMEFRAMES_DB догружает пропущенные свечи (после простоя бота)."""
    symbol = symbol or config.SYMBOL
    cursor = conn.cursor()
    totals: dict[str, int] = {}
    for tf in config.TIMEFRAMES_DB:
        try:
            totals[tf] = run_catch_up_for_timeframe(cursor, symbol, tf)
        except Exception as e:
            logger.exception("Догрузка ТФ %s: %s", tf, e)
            totals[tf] = 0
    conn.commit()
    return totals


def run_once(conn, backfill: bool = True) -> dict[str, int]:
    cursor = conn.cursor()
    symbol = config.SYMBOL
    totals = {}
    for tf in config.TIMEFRAMES_DB:
        try:
            if backfill:
                run_backfill_for_timeframe(cursor, symbol, tf)
            totals[tf] = run_update_for_timeframe(cursor, symbol, tf)
        except Exception as e:
            logger.exception("Ошибка по ТФ %s: %s", tf, e)
            totals[tf] = 0
    conn.commit()
    return totals


def main() -> None:
    setup_logging()
    if not config.TIMEFRAMES_DB:
        logger.error("Задайте TIMEFRAMES_DB в .env")
        return
    logger.info("Накопление БД | пара=%s | файл=%s", config.SYMBOL, get_db_path())
    init_db()
    conn = get_connection()
    run_once(conn, backfill=True)
    logger.info("Обновление каждые %s с. Ctrl+C — стоп.", config.DB_UPDATE_INTERVAL_SEC)
    try:
        while True:
            time.sleep(config.DB_UPDATE_INTERVAL_SEC)
            totals = run_once(conn, backfill=False)
            if any(totals.values()):
                logger.info("Добавлено: %s", totals)
    except KeyboardInterrupt:
        logger.info("Стоп.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
