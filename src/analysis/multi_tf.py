"""
Мультитаймфреймовый анализ: агрегация сигналов с нескольких таймфреймов.
Тренд на старшем ТФ + 6 фаз рынка (накопление, рост, распределение, падение, капитуляция, восстановление).
Источник свечей: DATA_SOURCE=db — из БД (по умолчанию), =exchange — запрос к Bybit на каждый тик.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..core import config
from ..core.exchange import get_klines_multi_timeframe
from .market_phases import BEARISH_PHASES, BULLISH_PHASES, detect_phase

logger = logging.getLogger(__name__)


def _load_candles_from_db(
    db_conn: sqlite3.Connection,
    symbol: str,
    intervals: list[str],
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Загружает последние limit свечей по каждому ТФ из БД. Формат как у get_klines_multi_timeframe."""
    from ..core.database import get_candles

    cursor = db_conn.cursor()
    out: dict[str, list[dict[str, Any]]] = {}
    for tf in intervals:
        try:
            rows = get_candles(cursor, symbol, tf, limit=limit, order_asc=False)
            out[tf] = rows  # уже от старых к новым
        except Exception as e:
            logger.warning("БД ТФ %s: %s", tf, e)
            out[tf] = []
    return out


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
    data_source: str | None = None,
    db_conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """
    Собирает данные по всем таймфреймам, тренды, 6 фаз и агрегированный сигнал.
    data_source: "db" | "exchange" | None (берётся из config.DATA_SOURCE).
    db_conn: при data_source="db" — соединение с БД; иначе используется биржа.
    """
    symbol = symbol or config.SYMBOL
    intervals = intervals or config.TIMEFRAMES
    if not intervals:
        return {
            "symbol": symbol,
            "timeframes": {},
            "higher_tf_trend": "flat",
            "signals": {"direction": "none", "reason": "no timeframes", "confidence": 0.0, "confidence_level": "—"},
        }

    src = (data_source or getattr(config, "DATA_SOURCE", "exchange") or "exchange").lower()
    if src == "db" and db_conn is not None:
        data = _load_candles_from_db(db_conn, symbol, intervals, limit=config.KLINE_LIMIT or 200)
    else:
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
    signal_min_conf = getattr(config, "SIGNAL_MIN_CONFIDENCE", 0.0)

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

    # Уверенность сигнала 0..1: от score фазы и от совпадения тренда с фазой
    confidence = 0.0
    if direction != "none":
        confidence = higher_tf_phase_score
        if higher_tf_trend != "flat":
            confidence = min(1.0, confidence + 0.1)
    if confidence >= 0.7:
        confidence_level = "strong"
    elif confidence >= 0.5:
        confidence_level = "medium"
    elif confidence > 0:
        confidence_level = "weak"
    else:
        confidence_level = "—"
    above_min = confidence >= signal_min_conf

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
            "confidence": round(confidence, 3),
            "confidence_level": confidence_level,
            "above_min_confidence": above_min,
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
