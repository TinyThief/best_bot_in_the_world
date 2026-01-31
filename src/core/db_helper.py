"""
Модуль-помощник для работы с БД свечей: умные выборки, проверка актуальности, кэш.
Позволяет не скачивать БД заново — только догружать нужный ТФ при необходимости.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from . import config
from .database import get_candles, get_latest_start_time
from ..scripts.accumulate_db import run_catch_up_for_timeframe, run_fill_gap_for_timeframe

logger = logging.getLogger(__name__)

# Кэш выборок: ключ (symbol, timeframe, days), значение (candles, timestamp)
# TTL секунд — не дергаем БД при повторных запросах (например /chart дважды за минуту)
_CACHE: dict[tuple[str, str, int], tuple[list[dict[str, Any]], float]] = {}
_CACHE_TTL_SEC = 60


def _normalize_ts_ms(ts: int) -> int:
    """Приводит start_time к миллисекундам (в БД от Bybit — уже мс)."""
    return int(ts) if ts > 1e10 else int(ts) * 1000


def get_last_candle_ts(conn: sqlite3.Connection, symbol: str, timeframe: str) -> int | None:
    """Возвращает start_time последней свечи в БД (мс) или None."""
    cur = conn.cursor()
    try:
        return get_latest_start_time(cur, symbol, timeframe)
    finally:
        pass  # не закрываем conn


def is_stale(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str,
    max_lag_sec: int = 86400,
) -> bool:
    """
    True, если последняя свеча в БД старше max_lag_sec (по умолчанию 1 сутки).
    Для графика «последние 2 года» можно не догружать каждый раз; для сигналов — догружать.
    """
    last_ts = get_last_candle_ts(conn, symbol, timeframe)
    if last_ts is None:
        return True
    last_ms = _normalize_ts_ms(last_ts)
    now_ms = int(time.time() * 1000)
    return (now_ms - last_ms) > max_lag_sec * 1000


def catch_up_tf(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str,
) -> int:
    """Догружает один таймфрейм с момента последней свечи до текущего времени. Возвращает число вставленных свечей."""
    cur = conn.cursor()
    try:
        n = run_catch_up_for_timeframe(cur, symbol, timeframe)
        conn.commit()
        return n
    except Exception as e:
        logger.exception("Догрузка ТФ %s для %s: %s", timeframe, symbol, e)
        conn.rollback()
        return 0


def get_candles_last_days(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str,
    days: int = 730,
    *,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Возвращает свечи за последние N дней (от последней свечи в БД).
    Порядок: от старых к новым. Для графика «последние 2 года» — days=730.
    При use_cache=True повторный запрос с теми же (symbol, tf, days) в течение _CACHE_TTL_SEC вернёт кэш.
    """
    cache_key = (symbol, timeframe, days)
    if use_cache and cache_key in _CACHE:
        cached_candles, cached_at = _CACHE[cache_key]
        if time.time() - cached_at < _CACHE_TTL_SEC:
            return cached_candles
        del _CACHE[cache_key]

    cur = conn.cursor()
    last_ts = get_latest_start_time(cur, symbol, timeframe)
    if last_ts is None:
        return []

    last_ms = _normalize_ts_ms(last_ts)
    cutoff_ms = last_ms - days * 24 * 3600 * 1000
    # Запрашиваем с запасом (выходные/праздники). Для 730 дней нужно не менее ~730 свечей; лимит 2000 чтобы не обрезать при пропусках в БД.
    limit = min(days + 200, 2000)
    rows = get_candles(cur, symbol, timeframe, limit=limit, order_asc=False)
    if not rows:
        return []
    # rows уже от старых к новым (после reverse в get_candles)
    out = [c for c in rows if _normalize_ts_ms(c["start_time"]) >= cutoff_ms]
    if use_cache:
        _CACHE[cache_key] = (out, time.time())
    return out


def ensure_fresh_then_get(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str,
    days: int = 730,
    max_lag_sec: int = 86400,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Если данные по ТФ устарели (последняя свеча старше max_lag_sec) — догружает этот ТФ до текущего момента,
    затем возвращает свечи за последние days дней. Так график получает актуальные данные без полной перезаливки БД.
    """
    if conn is None:
        return []
    if is_stale(conn, symbol, timeframe, max_lag_sec):
        n = catch_up_tf(conn, symbol, timeframe)
        if n:
            logger.info("БД: догружено ТФ %s для %s — %s свечей", timeframe, symbol, n)
        cache_key = (symbol, timeframe, days)
        _CACHE.pop(cache_key, None)
    candles = get_candles_last_days(conn, symbol, timeframe, days=days, use_cache=use_cache)
    # Если свечей заметно меньше ожидаемого (например пропуск в БД) — один раз дозаполняем пропуски и перезапрашиваем
    if candles and len(candles) < days * 0.6:
        try:
            cur = conn.cursor()
            filled = run_fill_gap_for_timeframe(cur, symbol, timeframe)
            conn.commit()
            if filled:
                logger.info("БД: дозаполнены пропуски ТФ %s для %s — %s свечей", timeframe, symbol, filled)
                _CACHE.pop((symbol, timeframe, days), None)
                candles = get_candles_last_days(conn, symbol, timeframe, days=days, use_cache=use_cache)
        except Exception as e:
            logger.warning("Дозаполнение пропусков ТФ %s для %s: %s", timeframe, symbol, e)
    return candles


# Ключ кэша «все свечи» — days=-1
_ALL_DAYS_KEY = -1


def ensure_fresh_then_get_all(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str,
    max_lag_sec: int = 86400,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Если данные по ТФ устарели — догружает этот ТФ до текущего момента,
    затем возвращает все свечи из БД (по максимуму). Порядок: от старых к новым.
    """
    if conn is None:
        return []
    cache_key = (symbol, timeframe, _ALL_DAYS_KEY)
    if use_cache and cache_key in _CACHE:
        cached_candles, cached_at = _CACHE[cache_key]
        if time.time() - cached_at < _CACHE_TTL_SEC:
            return cached_candles
        del _CACHE[cache_key]
    if is_stale(conn, symbol, timeframe, max_lag_sec):
        n = catch_up_tf(conn, symbol, timeframe)
        if n:
            logger.info("БД: догружено ТФ %s для %s — %s свечей", timeframe, symbol, n)
        _CACHE.pop(cache_key, None)
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=None, order_asc=True)
    if use_cache:
        _CACHE[cache_key] = (candles, time.time())
    return candles


def cache_clear() -> None:
    """Очистить кэш выборок (например после ручного обновления БД)."""
    _CACHE.clear()
    logger.debug("Кэш БД очищен")
