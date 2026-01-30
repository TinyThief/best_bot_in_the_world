"""
Клиент Bybit: получение свечей и базовая работа с рынком.
Используется REST API V5 через pybit.
Ретраи при rate limit (429/10006) и сетевых сбоях с экспоненциальной задержкой.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pybit.unified_trading import HTTP

from . import config

logger = logging.getLogger(__name__)

# Интервалы Bybit: 1,3,5,15,30,60,120,240,360,720,D,W,M
BYBIT_INTERVALS = frozenset({"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"})

# Ретраи при rate limit / сетевых сбоях
EXCHANGE_MAX_RETRIES = getattr(config, "EXCHANGE_MAX_RETRIES", 5)
EXCHANGE_RETRY_BACKOFF_SEC = getattr(config, "EXCHANGE_RETRY_BACKOFF_SEC", 1.0)

# Допустимый диапазон цен (USDT) по парам для linear — чтобы не записать мусор/ turnover вместо цены.
# Для BTC реальные цены исторически до ~100–125k; выше — ошибочные данные от API.
_PRICE_RANGE_BY_SYMBOL = {
    "BTCUSDT": (1_000.0, 150_000.0),
    "ETHUSDT": (100.0, 100_000.0),
}
_DEFAULT_PRICE_RANGE = (0.01, 50_000_000.0)


def _get_price_range(symbol: str, category: str) -> tuple[float, float]:
    """Возвращает (min_price, max_price) для проверки OHLC. Только linear."""
    if category != "linear":
        return _DEFAULT_PRICE_RANGE
    sym = (symbol or "").strip().upper()
    for key, rng in _PRICE_RANGE_BY_SYMBOL.items():
        if key in sym or sym in key:
            return rng
    return _DEFAULT_PRICE_RANGE


# Максимальный допустимый диапазон (high-low)/open. Для минутных свечей 30% отсекает мусор.
# Для D/W/M исторически бывают реальные 30–60% дневные диапазоны — используем 50%.
_MAX_OHLC_RANGE_RATIO = 0.30
_MAX_OHLC_RANGE_RATIO_DAILY = 0.50  # D, W, M


def _max_range_ratio_for_interval(interval: str | None) -> float:
    """Порог по диапазону: для дневных и старше — мягче."""
    if not interval:
        return _MAX_OHLC_RANGE_RATIO
    tf = str(interval).strip().upper()
    return _MAX_OHLC_RANGE_RATIO_DAILY if tf in ("D", "W", "M") else _MAX_OHLC_RANGE_RATIO


def _filter_valid_ohlc(
    candles: list[dict[str, Any]], symbol: str, category: str, interval: str | None = None
) -> list[dict[str, Any]]:
    """
    Отфильтровывает свечи с нереалистичными OHLC (цена вне диапазона, абсурдный диапазон).
    Для ТФ D/W/M порог диапазона мягче (50%), чтобы не отбрасывать реальные волатильные дни.
    В лог — только сводка (каждую отброшенную свечу пишем в DEBUG).
    """
    if not candles:
        return candles
    low_ok, high_ok = _get_price_range(symbol, category)
    max_ratio = _max_range_ratio_for_interval(interval)
    valid = []
    dropped = 0
    for c in candles:
        o, h, l, cl = c.get("open"), c.get("high"), c.get("low"), c.get("close")
        try:
            o, h, l, cl = float(o), float(h), float(l), float(cl)
        except (TypeError, ValueError):
            dropped += 1
            continue
        mn = min(o, h, l, cl)
        mx = max(o, h, l, cl)
        if mn < low_ok or mx > high_ok:
            dropped += 1
            logger.debug(
                "Свеча отброшена (цена вне %s–%s): symbol=%s ts=%s O=%.2f H=%.2f L=%.2f C=%.2f",
                low_ok, high_ok, symbol, c.get("start_time"), o, h, l, cl,
            )
            continue
        if o and o > 0:
            range_ratio = (h - l) / o
            if range_ratio > max_ratio:
                dropped += 1
                logger.debug(
                    "Свеча отброшена (диапазон %.1f%% > %.0f%%): symbol=%s ts=%s O=%.2f H=%.2f L=%.2f C=%.2f",
                    range_ratio * 100, max_ratio * 100, symbol, c.get("start_time"), o, h, l, cl,
                )
                continue
        valid.append(c)
    if dropped:
        logger.warning(
            "Отброшено свечей с неверным масштабом/диапазоном: %s (оставлено %s, ТФ=%s)",
            dropped, len(valid), interval or "—",
        )
    return valid


def _session() -> HTTP:
    """Единая сессия Bybit HTTP (только маркет-данные — ключи не обязательны)."""
    timeout = getattr(config, "EXCHANGE_REQUEST_TIMEOUT_SEC", 30)
    return HTTP(
        testnet=config.BYBIT_TESTNET,
        api_key=config.BYBIT_API_KEY or None,
        api_secret=config.BYBIT_API_SECRET or None,
        timeout=timeout,
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


def _is_rate_limit_or_retryable(out: dict | None, exc: Exception | None) -> bool:
    """Проверяет, нужно ли повторять запрос (rate limit или временная ошибка)."""
    if out is not None:
        code = out.get("retCode")
        msg = str(out.get("retMsg", "")).lower()
        if code == 10006 or code == 10007 or "rate" in msg or "too many" in msg or "limit" in msg:
            return True
        if code in (10016, 10017):  # сервис занят / таймаут
            return True
    if exc is not None:
        es = str(exc).lower()
        if "timeout" in es or "connection" in es or "network" in es or "429" in es or "503" in es or "502" in es:
            return True
    return False


def _request_kline(session: HTTP, **params: Any) -> dict:
    """Выполняет get_kline с ретраями при rate limit и сетевых ошибках."""
    last_err: Exception | None = None
    last_out: dict | None = None
    for attempt in range(EXCHANGE_MAX_RETRIES):
        try:
            out = session.get_kline(**params)
            last_out = out
            if out.get("retCode") == 0:
                return out
            if _is_rate_limit_or_retryable(out, None):
                wait = EXCHANGE_RETRY_BACKOFF_SEC * (2 ** attempt)
                logger.warning(
                    "Bybit API retCode=%s (попытка %s/%s), ждём %.1f с",
                    out.get("retCode"), attempt + 1, EXCHANGE_MAX_RETRIES, wait,
                )
                time.sleep(wait)
                last_err = RuntimeError(f"Bybit get_kline: {out.get('retMsg', out)}")
                continue
            raise RuntimeError(f"Bybit get_kline error: {out.get('retMsg', out)}")
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            if not _is_rate_limit_or_retryable(last_out, e) or attempt >= EXCHANGE_MAX_RETRIES - 1:
                raise
            wait = EXCHANGE_RETRY_BACKOFF_SEC * (2 ** attempt)
            logger.warning("Bybit запрос ошибка (попытка %s/%s): %s, ждём %.1f с", attempt + 1, EXCHANGE_MAX_RETRIES, e, wait)
            time.sleep(wait)
    raise last_err or RuntimeError("Bybit get_kline: retries exceeded")


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

    out = _request_kline(session, **params)

    raw_list = out.get("result", {}).get("list") or []
    parsed = _parse_kline_list(raw_list)
    return _filter_valid_ohlc(parsed, symbol, category, interval)


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
    max_candles: int | None = 100_000,
    limit_per_request: int = 1000,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """
    Подгружает историю свечей вглубь до end_ms, пагинируя по limit_per_request.
    Возвращает свечи в хронологическом порядке (старые → новые).
    Останавливается при достижении max_candles (если задан), или когда биржа больше не отдаёт данные.
    max_candles=None — без лимита, загрузка всего доступного диапазона.
    """
    category = category or config.BYBIT_CATEGORY
    interval = str(interval).strip()
    if interval not in BYBIT_INTERVALS:
        raise ValueError(f"Недопустимый интервал: {interval}")

    all_rows: list[dict[str, Any]] = []
    current_end = end_ms
    session = _session()

    while max_candles is None or len(all_rows) < max_candles:
        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit_per_request,
            "end": current_end,
        }
        out = _request_kline(session, **params)
        raw_list = out.get("result", {}).get("list") or []
        if not raw_list:
            break
        chunk = _parse_kline_list(raw_list)
        chunk = _filter_valid_ohlc(chunk, symbol, category, interval)
        if not chunk:
            break
        current_end = min(c["start_time"] for c in chunk) - 1
        all_rows = chunk + all_rows
        if len(chunk) < limit_per_request:
            break
        if max_candles is not None and len(all_rows) >= max_candles:
            break

    return all_rows[:max_candles] if max_candles is not None else all_rows
