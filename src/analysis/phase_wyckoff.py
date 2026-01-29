"""
Определение фазы рынка по методу Вайкоффа.

Только структура, объём у границ, spring/upthrust, позиция в диапазоне, zone freshness,
trend_strength, recent return, RSI (ограниченно). Без EMA/ADX/BB/OBV/VWAP в решении о фазе.

Интерфейс: detect_phase(candles, lookback=100, timeframe=None, higher_tf_phase=None, higher_tf_trend=None) -> dict
"""
from __future__ import annotations

from typing import Any

from .market_phases import (
    BEARISH_PHASES,
    BULLISH_PHASES,
    PHASE_NAMES_RU,
    PHASE_PROFILES,
    _apply_higher_tf_context,
    _clip_score,
    _price_position_in_range,
    _recent_return,
    _rsi,
    _rsi_divergence,
    _spring_upthrust,
    _structure,
    _tf_to_profile,
    _trend_strength,
    _volume_at_range_bounds,
    _volume_pressure_at_bounds,
    _volume_ratio,
    _zone_freshness,
)


def detect_phase(
    candles: list[dict[str, Any]],
    lookback: int = 100,
    vol_spike: float | None = None,
    drop_threshold: float | None = None,
    range_position_low: float | None = None,
    range_position_high: float | None = None,
    *,
    timeframe: str | None = None,
    higher_tf_phase: str | None = None,
    higher_tf_trend: str | None = None,
) -> dict[str, Any]:
    """
    Фаза рынка только по Вайкоффу: структура, объём у границ, spring/upthrust, позиция, RSI.
    Без индикаторов (EMA, ADX, BB, OBV, VWAP) в решении.
    """
    if timeframe is not None:
        prof = PHASE_PROFILES[_tf_to_profile(timeframe)]
        vol_spike = vol_spike if vol_spike is not None else prof["vol_spike"]
        drop_threshold = drop_threshold if drop_threshold is not None else prof["drop_threshold"]
        range_position_low = range_position_low if range_position_low is not None else prof["range_position_low"]
        range_position_high = range_position_high if range_position_high is not None else prof["range_position_high"]
    else:
        vol_spike = vol_spike if vol_spike is not None else 1.8
        drop_threshold = drop_threshold if drop_threshold is not None else -0.05
        range_position_low = range_position_low if range_position_low is not None else 0.35
        range_position_high = range_position_high if range_position_high is not None else 0.65

    if not candles or len(candles) < 30:
        return {
            "phase": "accumulation",
            "phase_ru": PHASE_NAMES_RU["accumulation"],
            "score": 0.0,
            "details": {"reason": "мало данных", "method": "wyckoff"},
        }

    c = candles[-lookback:] if len(candles) >= lookback else candles
    structure = _structure(c, pivots=5)
    position = _price_position_in_range(c, lookback=min(50, len(c)))
    vol_ratio = _volume_ratio(c, short=3, long=20)
    ret_5 = _recent_return(c, 5)
    ret_20 = _recent_return(c, min(20, len(c) - 1))
    rsi = _rsi(c, 14)
    lb = min(50, len(c))
    vol_at_low, vol_at_high = _volume_at_range_bounds(c, lookback=lb, band=0.15)
    buying_pressure, selling_pressure = _volume_pressure_at_bounds(c, lookback=lb, band=0.15)
    rsi_bull_div, rsi_bear_div = _rsi_divergence(c, period=14, window=min(20, len(c) // 2))
    spring, upthrust = _spring_upthrust(c, lookback=min(30, len(c)), tail=min(10, len(c) // 3))
    trend_strength = _trend_strength(c, 14)
    fresh_low, fresh_high = _zone_freshness(c, lookback=min(20, len(c)), band=0.2)

    details = {
        "method": "wyckoff",
        "structure": structure,
        "position_in_range": round(position, 3) if position is not None else None,
        "volume_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
        "volume_at_low": round(vol_at_low, 3) if vol_at_low is not None else None,
        "volume_at_high": round(vol_at_high, 3) if vol_at_high is not None else None,
        "volume_buying_pressure_low": round(buying_pressure, 3) if buying_pressure is not None else None,
        "volume_selling_pressure_high": round(selling_pressure, 3) if selling_pressure is not None else None,
        "rsi_bullish_divergence": rsi_bull_div,
        "rsi_bearish_divergence": rsi_bear_div,
        "spring": spring,
        "upthrust": upthrust,
        "trend_strength": round(trend_strength, 3) if trend_strength is not None else None,
        "fresh_low": fresh_low,
        "fresh_high": fresh_high,
        "return_5": round(ret_5, 4) if ret_5 is not None else None,
        "return_20": round(ret_20, 4) if ret_20 is not None else None,
        "rsi": round(rsi, 1) if rsi is not None else None,
    }

    pos = position if position is not None else 0.5
    vol_at_low_val = vol_at_low if vol_at_low is not None else 1.0
    vol_at_high_val = vol_at_high if vol_at_high is not None else 1.0
    buying_pressure_val = buying_pressure if buying_pressure is not None else 0.0
    selling_pressure_val = selling_pressure if selling_pressure is not None else 0.0
    trend_str = trend_strength if trend_strength is not None else 0.5
    vol = vol_ratio if vol_ratio is not None else 1.0
    r5 = ret_5 if ret_5 is not None else 0.0
    r20 = ret_20 if ret_20 is not None else 0.0
    rsi_val = rsi if rsi is not None else 50.0

    # Capitulation
    if r5 <= drop_threshold and vol >= vol_spike:
        sc = min(1.0, abs(r5) * 5 + (vol - 1) * 0.2)
        if rsi_val < 30:
            sc = _clip_score(sc + 0.05)
        sc = _apply_higher_tf_context("capitulation", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "capitulation", "phase_ru": PHASE_NAMES_RU["capitulation"], "score": sc, "details": details}

    # Recovery
    if r5 is not None and r20 is not None and r5 > 0.01 and r20 < -0.02:
        strength = min(1.0, (r5 - 0.01) / 0.02) * 0.5 + min(1.0, abs(r20) / 0.05) * 0.3
        sc = _clip_score(0.55 + strength)
        if rsi_val < 35:
            sc = _clip_score(sc + 0.08)
        if rsi_bull_div:
            sc = _clip_score(sc + 0.05)
        sc = _apply_higher_tf_context("recovery", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "recovery", "phase_ru": PHASE_NAMES_RU["recovery"], "score": sc, "details": details}

    # Markup (structure up)
    if structure == "up" and (r20 is None or r20 >= -0.01):
        strength = (r20 + 0.01) / 0.04 if r20 is not None else 0.5
        sc = _clip_score(0.65 + 0.2 * min(1.0, max(0.0, strength)))
        if rsi_val > 70:
            sc = _clip_score(sc - 0.1)
        if trend_str > 0.4:
            sc = _clip_score(sc + 0.03)
        elif trend_str < 0.2:
            sc = _clip_score(sc - 0.03)
        sc = _apply_higher_tf_context("markup", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}

    # Markdown (structure down)
    if structure == "down" and (r20 is None or r20 <= 0.01):
        strength = (-r20 + 0.01) / 0.04 if r20 is not None else 0.5
        sc = _clip_score(0.65 + 0.2 * min(1.0, max(0.0, strength)))
        if rsi_val < 30:
            sc = _clip_score(sc + 0.05)
        if rsi_bear_div:
            sc = _clip_score(sc + 0.03)
        if trend_str > 0.4:
            sc = _clip_score(sc + 0.03)
        elif trend_str < 0.2:
            sc = _clip_score(sc - 0.03)
        sc = _apply_higher_tf_context("markdown", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}

    # Range: accumulation / distribution
    if structure == "range":
        if position is not None and pos <= range_position_low:
            strength = 1.0 - (pos / max(0.01, range_position_low))
            sc = _clip_score(0.5 + 0.25 * strength)
            if vol_at_low_val > 1.15:
                sc = _clip_score(sc + 0.05)
            if buying_pressure_val > 1.15:
                sc = _clip_score(sc + 0.03)
            if rsi_bull_div:
                sc = _clip_score(sc + 0.04)
            if spring:
                sc = _clip_score(sc + 0.05)
            if trend_str < 0.3:
                sc = _clip_score(sc + 0.03)
            if fresh_low:
                sc = _clip_score(sc + 0.02)
            sc = _apply_higher_tf_context("accumulation", sc, higher_tf_phase, higher_tf_trend)
            return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}
        if position is not None and pos >= range_position_high:
            strength = (pos - range_position_high) / max(0.01, 1.0 - range_position_high)
            sc = _clip_score(0.5 + 0.25 * min(1.0, strength))
            if rsi_val > 70:
                sc = _clip_score(sc + 0.08)
            if vol_at_high_val > 1.15:
                sc = _clip_score(sc + 0.05)
            if selling_pressure_val > 1.15:
                sc = _clip_score(sc + 0.03)
            if rsi_bear_div:
                sc = _clip_score(sc + 0.04)
            if upthrust:
                sc = _clip_score(sc + 0.05)
            if trend_str < 0.3:
                sc = _clip_score(sc + 0.03)
            if fresh_high:
                sc = _clip_score(sc + 0.02)
            sc = _apply_higher_tf_context("distribution", sc, higher_tf_phase, higher_tf_trend)
            return {"phase": "distribution", "phase_ru": PHASE_NAMES_RU["distribution"], "score": sc, "details": details}
        if (r20 or 0) > 0.01:
            strength = min(1.0, ((r20 or 0) - 0.01) / 0.02)
            sc = _clip_score(0.4 + 0.2 * strength)
            if rsi_val > 70:
                sc = _clip_score(sc - 0.08)
            sc = _apply_higher_tf_context("markup", sc, higher_tf_phase, higher_tf_trend)
            return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}
        if (r20 or 0) < -0.01:
            strength = min(1.0, (abs(r20 or 0) - 0.01) / 0.02)
            sc = _clip_score(0.4 + 0.2 * strength)
            if rsi_val < 30:
                sc = _clip_score(sc + 0.05)
            if rsi_bear_div:
                sc = _clip_score(sc + 0.03)
            sc = _apply_higher_tf_context("markdown", sc, higher_tf_phase, higher_tf_trend)
            return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}
        sc = _apply_higher_tf_context("accumulation", 0.4, higher_tf_phase, higher_tf_trend)
        return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}

    # Fallback by return
    if (r20 or 0) > 0.02:
        strength = min(1.0, ((r20 or 0) - 0.02) / 0.05)
        sc = _clip_score(0.5 + 0.3 * strength)
        if rsi_val > 70:
            sc = _clip_score(sc - 0.1)
        sc = _apply_higher_tf_context("markup", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}
    if (r20 or 0) < -0.02:
        strength = min(1.0, (abs(r20 or 0) - 0.02) / 0.05)
        sc = _clip_score(0.5 + 0.3 * strength)
        if rsi_val < 30:
            sc = _clip_score(sc + 0.05)
        if rsi_bear_div:
            sc = _clip_score(sc + 0.03)
        sc = _apply_higher_tf_context("markdown", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}
    sc = _apply_higher_tf_context("accumulation", 0.3, higher_tf_phase, higher_tf_trend)
    return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}
