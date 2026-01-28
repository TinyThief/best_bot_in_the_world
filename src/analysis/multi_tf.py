"""
Мультитаймфреймовый анализ: агрегация сигналов с нескольких таймфреймов.
Тренд на старшем ТФ + 6 фаз рынка (накопление, рост, распределение, падение, капитуляция, восстановление).
"""
from __future__ import annotations

import logging
from typing import Any

from ..core import config
from ..core.exchange import get_klines_multi_timeframe
from .market_phases import BEARISH_PHASES, BULLISH_PHASES, detect_phase

logger = logging.getLogger(__name__)


def _trend_from_candles(candles: list[dict[str, Any]], lookback: int = 5) -> str:
    """"up" / "down" / "flat" по соотношению цен закрытия."""
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
    """Собирает данные по всем таймфреймам, тренды, 6 фаз и агрегированный сигнал."""
    symbol = symbol or config.SYMBOL
    intervals = intervals or config.TIMEFRAMES
    if not intervals:
        return {"symbol": symbol, "timeframes": {}, "higher_tf_trend": "flat", "signals": {"direction": "none", "reason": "no timeframes"}}

    data = get_klines_multi_timeframe(symbol=symbol, intervals=intervals)
    sorted_tfs = sorted(intervals, key=_tf_sort_key)
    higher_tf = sorted_tfs[-1] if sorted_tfs else None

    timeframes_report: dict[str, dict[str, Any]] = {}
    for tf in sorted_tfs:
        candles = data.get(tf) or []
        trend = _trend_from_candles(candles) if candles else "flat"
        phase_info = detect_phase(candles, timeframe=tf) if candles and len(candles) >= 30 else {"phase": "accumulation", "phase_ru": "—", "score": 0.0, "details": {}}
        timeframes_report[tf] = {
            "candles": candles,
            "trend": trend,
            "phase": phase_info["phase"],
            "phase_ru": phase_info["phase_ru"],
            "phase_score": phase_info.get("score", 0),
            "phase_details": phase_info.get("details", {}),
        }

    # Контекст старшего ТФ для младших: пересчёт фаз с higher_tf_phase / higher_tf_trend
    if higher_tf:
        higher_tf_data = timeframes_report.get(higher_tf) or {}
        h_phase = higher_tf_data.get("phase")
        h_trend = higher_tf_data.get("trend", "flat")
        for tf in sorted_tfs:
            if tf == higher_tf:
                continue
            candles = data.get(tf) or []
            if candles and len(candles) >= 30:
                phase_info = detect_phase(
                    candles, timeframe=tf, higher_tf_phase=h_phase, higher_tf_trend=h_trend
                )
                timeframes_report[tf]["phase"] = phase_info["phase"]
                timeframes_report[tf]["phase_ru"] = phase_info["phase_ru"]
                timeframes_report[tf]["phase_score"] = phase_info.get("score", 0)
                timeframes_report[tf]["phase_details"] = phase_info.get("details", {})
    higher_tf_trend = (timeframes_report.get(higher_tf) or {}).get("trend", "flat")
    higher_tf_data = timeframes_report.get(higher_tf) or {}
    higher_tf_phase = higher_tf_data.get("phase", "accumulation")
    higher_tf_phase_ru = higher_tf_data.get("phase_ru", "—")
    higher_tf_phase_score = higher_tf_data.get("phase_score", 0.0)
    phase_score_min = getattr(config, "PHASE_SCORE_MIN", 0.6)
    phase_ok = higher_tf_phase_score >= phase_score_min

    direction = "none"
    reason = f"старший ТФ {higher_tf}: {higher_tf_trend}, фаза {higher_tf_phase_ru}"
    if not phase_ok:
        reason = f"фаза {higher_tf_phase_ru} (score={higher_tf_phase_score:.2f} < {phase_score_min}) — не используем для входа"
    elif higher_tf_trend == "up":
        if higher_tf_phase in BULLISH_PHASES:
            direction = "long"
            reason = f"тренд на {higher_tf} вверх, фаза {higher_tf_phase_ru} — разрешён лонг"
        else:
            reason = f"тренд вверх, но фаза {higher_tf_phase_ru} не бычья — осторожно с лонгом"
    elif higher_tf_trend == "down":
        if higher_tf_phase in BEARISH_PHASES:
            direction = "short"
            reason = f"тренд на {higher_tf} вниз, фаза {higher_tf_phase_ru} — разрешён шорт"
        else:
            reason = f"тренд вниз, но фаза {higher_tf_phase_ru} не медвежья — осторожно с шортом"

    return {
        "symbol": symbol,
        "timeframes": timeframes_report,
        "higher_tf_trend": higher_tf_trend,
        "higher_tf_phase": higher_tf_phase,
        "higher_tf_phase_ru": higher_tf_phase_ru,
        "higher_tf_phase_score": higher_tf_phase_score,
        "signals": {
            "direction": direction,
            "reason": reason,
            "phase_ok": phase_ok,
            "phase_score_min": phase_score_min,
        },
    }


def _tf_sort_key(tf: str) -> tuple[int, str]:
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
