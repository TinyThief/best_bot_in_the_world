"""
Полный бэкфилл БД за весь доступный на Bybit период.
Загружает историю без лимита по каждому таймфрейму из TIMEFRAMES_DB.
"""
from __future__ import annotations

import argparse
import logging
import time

from ..core import config
from ..core.logging_config import setup_logging
from ..core.database import (
    delete_klines_for_symbol,
    get_connection,
    get_db_path,
    get_latest_start_time,
    get_oldest_start_time,
    init_db,
    insert_candles,
)
from ..core.exchange import fetch_klines_backfill

logger = logging.getLogger(__name__)


def full_backfill_one_tf(cursor, symbol: str, timeframe: str, category: str) -> int:
    end_ms = int(time.time() * 1000)
    logger.info("Загрузка ТФ %s для %s (без лимита)...", timeframe, symbol)
    candles = fetch_klines_backfill(
        symbol=symbol,
        interval=timeframe,
        end_ms=end_ms,
        max_candles=None,
        limit_per_request=1000,
        category=category,
    )
    n = insert_candles(cursor, symbol, timeframe, candles)
    logger.info("  ТФ %s: загружено %s, вставлено %s", timeframe, len(candles), n)
    return n


def extend_backward_one_tf(cursor, symbol: str, timeframe: str, category: str) -> int:
    oldest = get_oldest_start_time(cursor, symbol, timeframe)
    if oldest is None:
        return full_backfill_one_tf(cursor, symbol, timeframe, category)
    end_ms = oldest - 1
    logger.info("Углубление ТФ %s для %s (до %s)...", timeframe, symbol, end_ms)
    candles = fetch_klines_backfill(
        symbol=symbol,
        interval=timeframe,
        end_ms=end_ms,
        max_candles=None,
        limit_per_request=1000,
        category=category,
    )
    n = insert_candles(cursor, symbol, timeframe, candles)
    logger.info("  ТФ %s: загружено %s, вставлено %s", timeframe, len(candles), n)
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="Полный бэкфилл БД за весь период Bybit")
    parser.add_argument("--clear", action="store_true", help="Удалить все данные по SYMBOL и загрузить заново")
    parser.add_argument("--extend", action="store_true", help="Только углубить историю по уже имеющимся ТФ")
    args = parser.parse_args()

    setup_logging()
    if not config.TIMEFRAMES_DB:
        logger.error("Задайте TIMEFRAMES_DB в .env. Пример: 1,3,5,15,30,60,120,240,360,720,D,W,M")
        return

    symbol = config.SYMBOL
    category = config.BYBIT_CATEGORY
    logger.info("Полный бэкфилл | пара=%s | категория=%s | таймфреймы=%s | файл=%s", symbol, category, config.TIMEFRAMES_DB, get_db_path())

    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    if args.clear:
        deleted = delete_klines_for_symbol(cursor, symbol)
        conn.commit()
        logger.info("Удалено свечей по %s: %s", symbol, deleted)

    for tf in config.TIMEFRAMES_DB:
        try:
            if args.extend:
                extend_backward_one_tf(cursor, symbol, tf, category)
            else:
                if args.clear or get_latest_start_time(cursor, symbol, tf) is None:
                    full_backfill_one_tf(cursor, symbol, tf, category)
                else:
                    extend_backward_one_tf(cursor, symbol, tf, category)
        except Exception as e:
            logger.exception("Ошибка по ТФ %s: %s", tf, e)
        conn.commit()

    conn.close()
    logger.info("Готово.")


if __name__ == "__main__":
    main()
