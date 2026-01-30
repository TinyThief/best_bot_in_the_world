"""
Перезалив дневного таймфрейма (D) с биржи Bybit.

Удаляет все свечи по SYMBOL и ТФ D из БД, затем загружает историю заново через API.
Используется для исправления данных (например, когда в БД попал неправильный масштаб цен).
"""
from __future__ import annotations

import logging
import time

from ..core import config
from ..core.database import (
    delete_klines_for_symbol_timeframe,
    get_connection,
    get_db_path,
    insert_candles,
)
from ..core.exchange import fetch_klines_backfill

logger = logging.getLogger(__name__)


def refill_tf_d(
    symbol: str | None = None,
    timeframe: str = "D",
    max_candles: int | None = None,
) -> tuple[int, int]:
    """
    Удаляет свечи по паре и ТФ из БД, загружает заново с Bybit.
    Возвращает (удалено, вставлено).
    """
    symbol = symbol or config.SYMBOL
    max_candles = max_candles or getattr(config, "BACKFILL_MAX_CANDLES", 50000)
    category = config.BYBIT_CATEGORY

    conn = get_connection()
    cur = conn.cursor()
    deleted = delete_klines_for_symbol_timeframe(cur, symbol, timeframe)
    conn.commit()
    logger.info("Удалено свечей ТФ %s: %s", timeframe, deleted)

    end_ms = int(time.time() * 1000)
    candles = fetch_klines_backfill(
        symbol=symbol,
        interval=timeframe,
        end_ms=end_ms,
        max_candles=max_candles,
        limit_per_request=1000,
        category=category,
    )
    inserted = insert_candles(cur, symbol, timeframe, candles)
    conn.commit()
    conn.close()
    logger.info("Загружено с биржи: %s, вставлено: %s", len(candles), inserted)
    return deleted, inserted


def main() -> None:
    from ..core.logging_config import setup_logging

    setup_logging()
    symbol = config.SYMBOL
    logger.info("Перезалив ТФ D для %s | БД: %s", symbol, get_db_path())
    deleted, inserted = refill_tf_d(symbol=symbol, timeframe="D")
    print(f"Готово: удалено {deleted}, вставлено {inserted} дневных свечей для {symbol}.")
