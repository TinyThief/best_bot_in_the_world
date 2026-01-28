"""
Клиент Bybit: получение свечей и базовая работа с рынком.
Используется REST API V5 через pybit.
"""
from __future__ import annotations

import logging
from typing import Any

from pybit.unified_trading import HTTP

import config

logger = logging.getLogger(__name__)

# Интервалы Bybit: 1,3,5,15,30,60,120,240,360,720,D,W,M
BYBIT_INTERVALS = frozenset({"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"})


def _session() -> HTTP:
    """Единая сессия Bybit HTTP (только маркет-данные — ключи не обязательны)."""
    return HTTP(
        testnet=config.BYBIT_TESTNET,
        api_key=config.BYBIT_API_KEY or None,
        api_secret=config.BYBIT_API_SECRET or None,
    )


def _parse_kline_list(raw_list: list) -> list[dict[str, Any]]:
    """Преобразует ответ Bybit [startTime,o,h,l,c,vol,turnover] в список dict. Хронологический порядок (старые → новые)."""
    rows = []
    for item in reversed(raw_list):
        rows.append({
            "start_time": int(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
        })
    return rows


def get_klines(
    symbol: str | None = None,
    interval: str = "15",
    category: str | None = None,
    limit: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> list[dict[str, Any]]:
    """
    Загружает свечи по паре и интервалу.
    Без start/end — последние limit свечей. С start/end — диапазон (для бэкфилла).
    Возвращает список словарей: start_time, open, high, low, close, volume.
    Свечи в хронологическом порядке (от старых к новым).
    """
    symbol = symbol or config.SYMBOL
    category = category or config.BYBIT_CATEGORY
    limit = limit or config.KLINE_LIMIT
    interval = str(interval).strip()
    if interval not in BYBIT_INTERVALS:
        raise ValueError(f"Недопустимый интервал Bybit: {interval}. Допустимы: {sorted(BYBIT_INTERVALS)}")

    session = _session()
    params = {
        "category": category,
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if start_ms is not None:
        params["start"] = start_ms
    if end_ms is not None:
        params["end"] = end_ms

    out = session.get_kline(**params)

    if out.get("retCode") != 0:
        raise RuntimeError(f"Bybit get_kline error: {out.get('retMsg', out)}")

    raw_list = out.get("result", {}).get("list") or []
    return _parse_kline_list(raw_list)


def get_klines_multi_timeframe(
    symbol: str | None = None,
    intervals: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Загружает свечи по нескольким таймфреймам.
    Возвращает словарь: { "15": [...], "60": [...], "240": [...] }.
    """
    symbol = symbol or config.SYMBOL
    intervals = intervals or config.TIMEFRAMES
    result: dict[str, list[dict[str, Any]]] = {}
    for tf in intervals:
        try:
            result[tf] = get_klines(symbol=symbol, interval=tf)
        except Exception as e:
            logger.exception("Ошибка загрузки свечей tf=%s: %s", tf, e)
            result[tf] = []
    return result


def fetch_klines_backfill(
    symbol: str,
    interval: str,
    end_ms: int,
    max_candles: int = 100_000,
    limit_per_request: int = 1000,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """
    Подгружает историю свечей вглубь до end_ms, пагинируя по limit_per_request.
    Возвращает свечи в хронологическом порядке (старые → новые).
    Останавливается при достижении max_candles или когда биржа больше не отдаёт данные.
    """
    category = category or config.BYBIT_CATEGORY
    interval = str(interval).strip()
    if interval not in BYBIT_INTERVALS:
        raise ValueError(f"Недопустимый интервал: {interval}")

    all_rows: list[dict[str, Any]] = []
    current_end = end_ms
    session = _session()

    while len(all_rows) < max_candles:
        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit_per_request,
            "end": current_end,
        }
        out = session.get_kline(**params)
        if out.get("retCode") != 0:
            raise RuntimeError(f"Bybit get_kline error: {out.get('retMsg', out)}")
        raw_list = out.get("result", {}).get("list") or []
        if not raw_list:
            break
        chunk = _parse_kline_list(raw_list)
        # следующий запрос — строго до самой старой из полученных
        current_end = min(c["start_time"] for c in chunk) - 1
        all_rows = chunk + all_rows
        if len(chunk) < limit_per_request:
            break

    return all_rows[:max_candles]
