"""
Синхронизация БД с биржей во время работы бота.
При старте: бэкфилл (если нет данных) + догрузка пропущенных свечей.
В цикле: обновление каждые DB_UPDATE_INTERVAL_SEC.
"""
from __future__ import annotations

import logging
import sqlite3
import time

from ..core import config
from ..core.database import get_connection, init_db
from ..scripts.accumulate_db import run_catch_up, run_extend_until_done, run_once

logger = logging.getLogger(__name__)


def open_and_prepare() -> sqlite3.Connection | None:
    """
    Инициализирует БД, делает бэкфилл по пустым ТФ и догружает пропуски за время простоя.
    Возвращает соединение для последующих вызовов refresh_if_due или None, если TIMEFRAMES_DB пуст.
    """
    if not config.TIMEFRAMES_DB:
        return None
    init_db()
    conn = get_connection()
    logger.info("БД: бэкфилл и догрузка пропусков...")
    run_once(conn, backfill=True)
    catch_totals = run_catch_up(conn)
    if any(catch_totals.values()):
        logger.info("БД: догружено пропусков %s", catch_totals)
    if config.AUTO_EXTEND_AT_STARTUP:
        logger.info("БД: углубление истории по всем ТФ...")
        extend_totals = run_extend_until_done(conn)
        if any(extend_totals.values()):
            logger.info("БД: углублено %s", extend_totals)
    return conn


def refresh_if_due(conn: sqlite3.Connection | None, last_refresh_ts: float) -> float:
    """
    Если прошло DB_UPDATE_INTERVAL_SEC с last_refresh_ts — подтягивает новые свечи по всем ТФ.
    Возвращает актуальный last_refresh_ts (time.time() после обновления или старый ts).
    """
    if conn is None:
        return last_refresh_ts
    now = time.time()
    if now - last_refresh_ts < config.DB_UPDATE_INTERVAL_SEC:
        return last_refresh_ts
    totals = run_once(conn, backfill=False)
    if any(totals.values()):
        logger.info("БД: добавлено %s", totals)
    return time.time()


def close(conn: sqlite3.Connection | None) -> None:
    """Закрывает соединение с БД, если оно открыто."""
    if conn is not None:
        conn.close()
        logger.info("БД: соединение закрыто")
