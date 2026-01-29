"""
Определение фазы рынка только по индикаторам.

EMA 20/50/200, ADX(14), ширина Bollinger Bands, RSI(14), OBV slope, VWAP (rolling).
Без структуры Вайкоффа и без price action (BOS/CHOCH).

Интерфейс: detect_phase(candles, lookback=100, timeframe=None, ...) -> dict
"""
from __future__ import annotations

from typing import Any

from .market_phases import (
    BEARISH_PHASES,
    BULLISH_PHASES,
    PHASE_NAMES_RU,
    _adx,
    _bb_width,
    _ema_stack,
    _obv_slope,
    _price_position_in_range,
    _recent_return,
    _rsi,
    _vwap_rolling,
    _volume_ratio,
)


def _clip_score(x: float) -> float:
    return min(1.0, max(0.0, x))


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
    Фаза рынка только по индикаторам: EMA, ADX, BB width, RSI, OBV slope, VWAP.
    Без структуры и объёма у границ Вайкоффа.
    """
    if not candles or len(candles) < 30:
        return {
            "phase": "accumulation",
            "phase_ru": PHASE_NAMES_RU["accumulation"],
            "score": 0.0,
            "details": {"reason": "мало данных", "method": "indicators"},
        }

    c = candles[-lookback:] if len(candles) >= lookback else candles
    lb = min(50, len(c))

    ema_stack = _ema_stack(c)
    adx_val, plus_di, minus_di = _adx(c, 14)
    bb_width = _bb_width(c, 20, 2.0)
    rsi = _rsi(c, 14)
    obv_slope = _obv_slope(c, 14) if len(c) >= 15 else None
    vwap_val, vwap_distance = _vwap_rolling(c, lb)
    position = _price_position_in_range(c, lookback=lb)
    vol_ratio = _volume_ratio(c, short=3, long=20)
    ret_5 = _recent_return(c, 5)
    ret_20 = _recent_return(c, min(20, len(c) - 1))

    ema_trend = ema_stack.get("ema_trend")
    adx = adx_val if adx_val is not None else 0.0
    bb_w = bb_width if bb_width is not None else 0.05
    rsi_val = rsi if rsi is not None else 50.0
    obv_s = obv_slope if obv_slope is not None else 0.0
    vwap_dist = vwap_distance if vwap_distance is not None else 0.0
    pos = position if position is not None else 0.5
    vol = vol_ratio if vol_ratio is not None else 1.0
    r5 = ret_5 if ret_5 is not None else 0.0
    r20 = ret_20 if ret_20 is not None else 0.0

    details = {
        "method": "indicators",
        "ema_trend": ema_trend,
        "adx": round(adx_val, 2) if adx_val is not None else None,
        "plus_di": round(plus_di, 2) if plus_di is not None else None,
        "minus_di": round(minus_di, 2) if minus_di is not None else None,
        "bb_width": round(bb_width, 4) if bb_width is not None else None,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "obv_slope": round(obv_slope, 4) if obv_slope is not None else None,
        "vwap_distance": round(vwap_distance, 4) if vwap_distance is not None else None,
        "position_in_range": round(position, 3) if position is not None else None,
        "return_5": round(ret_5, 4) if ret_5 is not None else None,
        "return_20": round(ret_20, 4) if ret_20 is not None else None,
    }

    drop_th = drop_threshold if drop_threshold is not None else -0.05
    vol_sp = vol_spike if vol_spike is not None else 1.8
    range_low = range_position_low if range_position_low is not None else 0.35
    range_high = range_position_high if range_position_high is not None else 0.65

    # Capitulation: резкое падение + всплеск объёма + RSI экстремально низкий
    if r5 <= drop_th and vol >= vol_sp and rsi_val < 30:
        sc = _clip_score(min(1.0, abs(r5) * 4 + (vol - 1) * 0.15))
        return {"phase": "capitulation", "phase_ru": PHASE_NAMES_RU["capitulation"], "score": sc, "details": details}

    # Recovery: недавний отскок (r5 > 0, r20 < 0), RSI выходит из перепроданности, цена выше VWAP или OBV вверх
    if r5 is not None and r20 is not None and r5 > 0.008 and r20 < -0.015:
        sc = 0.5 + 0.2 * min(1.0, r5 / 0.02) + 0.2 * min(1.0, abs(r20) / 0.04)
        if rsi_val < 40:
            sc += 0.05
        if vwap_dist > 0 or obv_s > 0.03:
            sc += 0.05
        sc = _clip_score(sc)
        return {"phase": "recovery", "phase_ru": PHASE_NAMES_RU["recovery"], "score": sc, "details": details}

    # Markup: бычий стек EMA + тренд (ADX) + цена выше VWAP + OBV вверх + RSI не перекуплен
    if ema_trend == "bullish" and adx > 22:
        sc = 0.55 + 0.15 * min(1.0, (adx - 22) / 30)
        if plus_di is not None and minus_di is not None and plus_di > minus_di:
            sc += 0.08
        if vwap_dist > 0:
            sc += 0.05
        if obv_s > 0.03:
            sc += 0.05
        if 40 <= rsi_val <= 65:
            sc += 0.05
        elif rsi_val > 70:
            sc -= 0.1
        sc = _clip_score(sc)
        return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}

    # Markdown: медвежий стек EMA + тренд + цена ниже VWAP + OBV вниз
    if ema_trend == "bearish" and adx > 22:
        sc = 0.55 + 0.15 * min(1.0, (adx - 22) / 30)
        if plus_di is not None and minus_di is not None and minus_di > plus_di:
            sc += 0.08
        if vwap_dist < 0:
            sc += 0.05
        if obv_s < -0.03:
            sc += 0.05
        if 35 <= rsi_val <= 60:
            sc += 0.03
        elif rsi_val < 25:
            sc += 0.05
        sc = _clip_score(sc)
        return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}

    # Accumulation: низкий ADX (флэт), сжатие BB, цена у низа диапазона, RSI не высокий
    if adx < 20 and bb_w < 0.06 and pos <= range_low:
        sc = 0.45 + 0.25 * (1.0 - pos / max(0.01, range_low))
        if rsi_val < 45:
            sc += 0.05
        if bb_w < 0.04:
            sc += 0.05
        sc = _clip_score(sc)
        return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}

    # Distribution: низкий ADX, сжатие BB, цена у верха диапазона, RSI не низкий
    if adx < 20 and bb_w < 0.06 and pos >= range_high:
        sc = 0.45 + 0.25 * (pos - range_high) / max(0.01, 1.0 - range_high)
        if rsi_val > 55:
            sc += 0.05
        if bb_w < 0.04:
            sc += 0.05
        sc = _clip_score(sc)
        return {"phase": "distribution", "phase_ru": PHASE_NAMES_RU["distribution"], "score": sc, "details": details}

    # Fallback по направлению индикаторов
    if ema_trend == "bullish" or (vwap_dist > 0 and obv_s > 0):
        sc = _clip_score(0.45 + 0.15 * (1 if ema_trend == "bullish" else 0) + 0.1 * (1 if vwap_dist > 0 else 0))
        return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}
    if ema_trend == "bearish" or (vwap_dist < 0 and obv_s < 0):
        sc = _clip_score(0.45 + 0.15 * (1 if ema_trend == "bearish" else 0) + 0.1 * (1 if vwap_dist < 0 else 0))
        return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}

    if pos <= 0.5:
        sc = _clip_score(0.35 + 0.2 * (1 - pos))
        return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}
    sc = _clip_score(0.35 + 0.2 * pos)
    return {"phase": "distribution", "phase_ru": PHASE_NAMES_RU["distribution"], "score": sc, "details": details}
