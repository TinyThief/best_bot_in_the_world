"""
Мультитаймфреймовый анализ: агрегация сигналов с нескольких таймфреймов.
Сейчас — заготовка под логику «тренд на старшем ТФ + вход на младшем».
"""
from __future__ import annotations

import logging
from typing import Any

import config
from exchange import get_klines_multi_timeframe

logger = logging.getLogger(__name__)


def _trend_from_candles(candles: list[dict[str, Any]], lookback: int = 5) -> str:
    """
    Упрощённый индикатор тренда по последним свечам.
    "up" / "down" / "flat" по соотношению цен закрытия.
    """
    if not candles or len(candles) < lookback:
        return "flat"
    recent = candles[-lookback:]
    closes = [c["close"] for c in recent]
    first = sum(closes[: len(closes) // 2]) / max(1, len(closes) // 2)
    last = sum(closes[len(closes) // 2 :]) / max(1, len(closes) - len(closes) // 2)
    if last > first * 1.002:
        return "up"
    if last < first * 0.998:
        return "down"
    return "flat"


def analyze_multi_timeframe(
    symbol: str | None = None,
    intervals: list[str] | None = None,
) -> dict[str, Any]:
    """
    Собирает данные по всем таймфреймам и возвращает агрегированный отчёт.
    Структура: {
        "symbol": str,
        "timeframes": { "15": { "candles": [...], "trend": "up"|"down"|"flat" }, ... },
        "higher_tf_trend": str,   # тренд старшего ТФ
        "signals": { "direction": "long"|"short"|"none", "reason": str },
    }
    """
    symbol = symbol or config.SYMBOL
    intervals = intervals or config.TIMEFRAMES
    if not intervals:
        return {"symbol": symbol, "timeframes": {}, "higher_tf_trend": "flat", "signals": {"direction": "none", "reason": "no timeframes"}}

    data = get_klines_multi_timeframe(symbol=symbol, intervals=intervals)
    timeframes_report: dict[str, dict[str, Any]] = {}
    for tf, candles in data.items():
        trend = _trend_from_candles(candles) if candles else "flat"
        timeframes_report[tf] = {"candles": candles, "trend": trend}

    # Старший таймфрейм — последний в списке (если сортируем по возрастанию — то максимальный)
    sorted_tfs = sorted(intervals, key=_tf_sort_key)
    higher_tf = sorted_tfs[-1] if sorted_tfs else None
    higher_tf_trend = (timeframes_report.get(higher_tf) or {}).get("trend", "flat")

    # Простая логика: лонг только если старший ТФ вверх, шорт — если вниз
    direction = "none"
    reason = f"старший ТФ {higher_tf}: {higher_tf_trend}"
    if higher_tf_trend == "up":
        direction = "long"
        reason = f"тренд на {higher_tf} вверх — разрешён лонг"
    elif higher_tf_trend == "down":
        direction = "short"
        reason = f"тренд на {higher_tf} вниз — разрешён шорт"

    return {
        "symbol": symbol,
        "timeframes": timeframes_report,
        "higher_tf_trend": higher_tf_trend,
        "signals": {"direction": direction, "reason": reason},
    }


def _tf_sort_key(tf: str) -> tuple[int, str]:
    """Сортировка таймфреймов: минуты числом, затем D, W, M."""
    if tf == "D":
        return (1_000_000, "D")
    if tf == "W":
        return (2_000_000, "W")
    if tf == "M":
        return (3_000_000, "M")
    try:
        return (int(tf), tf)
    except ValueError:
        return (0, tf)
