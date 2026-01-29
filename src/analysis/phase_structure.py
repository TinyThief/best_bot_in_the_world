"""
Определение фазы рынка по price action и рыночной структуре.

Свинг-точки (pivot high/low), Break of Structure (BOS), Change of Character (CHOCH).
Без индикаторов и без объёма у границ Вайкоффа.

Интерфейс: detect_phase(candles, lookback=100, timeframe=None, ...) -> dict
"""
from __future__ import annotations

from typing import Any

from .market_phases import PHASE_NAMES_RU, _clip_score, _recent_return, _volume_ratio


def _pivot_highs_lows(
    candles: list[dict[str, Any]], left: int = 2, right: int = 2
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Свинг-точки: pivot high = high больше left баров слева и right справа; pivot low — наоборот.
    Возвращает ([(index, price), ...], [(index, price), ...]) для highs и lows.
    """
    if not candles or len(candles) < left + right + 1:
        return [], []
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    pivot_highs: list[tuple[int, float]] = []
    pivot_lows: list[tuple[int, float]] = []
    for i in range(left, len(candles) - right):
        if all(highs[i] >= highs[i - j] for j in range(1, left + 1)) and all(
            highs[i] >= highs[i + j] for j in range(1, right + 1)
        ):
            pivot_highs.append((i, highs[i]))
        if all(lows[i] <= lows[i - j] for j in range(1, left + 1)) and all(
            lows[i] <= lows[i + j] for j in range(1, right + 1)
        ):
            pivot_lows.append((i, lows[i]))
    return pivot_highs, pivot_lows


def _structure_from_pivots(
    pivot_highs: list[tuple[int, float]],
    pivot_lows: list[tuple[int, float]],
    min_pivots: int = 3,
) -> str:
    """
    По последним min_pivots свингам: 'up' (HH+HL), 'down' (LH+LL), 'range'.
    """
    if len(pivot_highs) < min_pivots or len(pivot_lows) < min_pivots:
        return "range"
    last_highs = [p[1] for p in pivot_highs[-min_pivots:]]
    last_lows = [p[1] for p in pivot_lows[-min_pivots:]]
    hh = all(last_highs[i] >= last_highs[i - 1] * 0.998 for i in range(1, len(last_highs)))
    hl = all(last_lows[i] >= last_lows[i - 1] * 0.998 for i in range(1, len(last_lows)))
    lh = all(last_highs[i] <= last_highs[i - 1] * 1.002 for i in range(1, len(last_highs)))
    ll = all(last_lows[i] <= last_lows[i - 1] * 1.002 for i in range(1, len(last_lows)))
    if hh and hl:
        return "up"
    if lh and ll:
        return "down"
    return "range"


def _bos_choch(
    candles: list[dict[str, Any]],
    pivot_highs: list[tuple[int, float]],
    pivot_lows: list[tuple[int, float]],
    structure: str,
) -> tuple[bool, bool, bool, bool]:
    """
    BOS up, BOS down, CHOCH bullish (первый HL после downtrend), CHOCH bearish (первый LH после uptrend).
    Возвращает (bos_up, bos_down, choch_bullish, choch_bearish).
    """
    if not candles or not pivot_highs or not pivot_lows:
        return False, False, False, False
    last_close = candles[-1]["close"]
    last_high = candles[-1]["high"]
    last_low = candles[-1]["low"]
    last_swing_high = pivot_highs[-1][1]
    last_swing_low = pivot_lows[-1][1]
    bos_up = last_high > last_swing_high or last_close > last_swing_high
    bos_down = last_low < last_swing_low or last_close < last_swing_low

    choch_bullish = False
    choch_bearish = False
    if len(pivot_lows) >= 2 and structure == "down":
        # После медвежьей структуры: последний low выше предыдущего = HL = CHOCH
        if pivot_lows[-1][1] > pivot_lows[-2][1]:
            choch_bullish = True
    if len(pivot_highs) >= 2 and structure == "up":
        if pivot_highs[-1][1] < pivot_highs[-2][1]:
            choch_bearish = True

    return bos_up, bos_down, choch_bullish, choch_bearish


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
    Фаза рынка только по price action: свинг-точки, BOS, CHOCH.
    Без индикаторов и без объёма у границ.
    """
    if not candles or len(candles) < 40:
        return {
            "phase": "accumulation",
            "phase_ru": PHASE_NAMES_RU["accumulation"],
            "score": 0.0,
            "details": {"reason": "мало данных", "method": "structure"},
        }

    c = candles[-lookback:] if len(candles) >= lookback else candles
    pivot_highs, pivot_lows = _pivot_highs_lows(c, left=2, right=2)
    structure = _structure_from_pivots(pivot_highs, pivot_lows, min_pivots=3)
    bos_up, bos_down, choch_bullish, choch_bearish = _bos_choch(c, pivot_highs, pivot_lows, structure)

    ret_5 = _recent_return(c, 5)
    ret_20 = _recent_return(c, min(20, len(c) - 1))
    vol_ratio = _volume_ratio(c, short=3, long=20)
    r5 = ret_5 if ret_5 is not None else 0.0
    r20 = ret_20 if ret_20 is not None else 0.0
    vol = vol_ratio if vol_ratio is not None else 1.0
    drop_th = drop_threshold if drop_threshold is not None else -0.05
    vol_sp = vol_spike if vol_spike is not None else 1.8

    details = {
        "method": "structure",
        "structure": structure,
        "bos_up": bos_up,
        "bos_down": bos_down,
        "choch_bullish": choch_bullish,
        "choch_bearish": choch_bearish,
        "pivot_highs_count": len(pivot_highs),
        "pivot_lows_count": len(pivot_lows),
        "return_5": round(ret_5, 4) if ret_5 is not None else None,
        "return_20": round(ret_20, 4) if ret_20 is not None else None,
    }

    # Capitulation: резкий пробой вниз + всплеск объёма (финальная капитуляция перед возможным CHOCH)
    if r5 <= drop_th and vol >= vol_sp and structure == "down" and not choch_bullish:
        sc = _clip_score(min(1.0, abs(r5) * 4 + (vol - 1) * 0.15))
        return {"phase": "capitulation", "phase_ru": PHASE_NAMES_RU["capitulation"], "score": sc, "details": details}

    # Recovery: CHOCH бычий после downtrend + отскок (r5 > 0)
    if choch_bullish and (r5 > 0.005 or r20 < -0.02):
        sc = 0.55 + 0.2 * min(1.0, max(0, r5) / 0.02) + (0.1 if bos_up else 0.0)
        sc = _clip_score(sc)
        return {"phase": "recovery", "phase_ru": PHASE_NAMES_RU["recovery"], "score": sc, "details": details}

    # Markup: бычья структура + BOS вверх
    if structure == "up" and bos_up:
        sc = 0.65 + 0.2 * (0.5 + (0.5 if r20 is not None and r20 >= -0.01 else 0))
        sc = _clip_score(sc)
        return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}

    # Markdown: медвежья структура + BOS вниз
    if structure == "down" and bos_down and not choch_bullish:
        sc = 0.65 + 0.2 * (0.5 + (0.5 if r20 is not None and r20 <= 0.01 else 0))
        sc = _clip_score(sc)
        return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}

    # Accumulation: CHOCH бычий, но ещё не BOS вверх (зона накопления)
    if choch_bullish and not bos_up:
        sc = _clip_score(0.5 + 0.2 * min(1.0, max(0, r5) / 0.01))
        return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}

    # Distribution: CHOCH медвежий, но ещё не BOS вниз
    if choch_bearish and not bos_down:
        sc = _clip_score(0.5 + 0.2 * min(1.0, max(0, -r5) / 0.01))
        return {"phase": "distribution", "phase_ru": PHASE_NAMES_RU["distribution"], "score": sc, "details": details}

    # Fallback по структуре без явного BOS/CHOCH
    if structure == "up":
        sc = _clip_score(0.45 + 0.15 * (1 if r20 is not None and r20 > -0.02 else 0))
        return {"phase": "markup", "phase_ru": PHASE_NAMES_RU["markup"], "score": sc, "details": details}
    if structure == "down":
        sc = _clip_score(0.45 + 0.15 * (1 if r20 is not None and r20 < 0.02 else 0))
        return {"phase": "markdown", "phase_ru": PHASE_NAMES_RU["markdown"], "score": sc, "details": details}

    sc = _clip_score(0.35)
    return {"phase": "accumulation", "phase_ru": PHASE_NAMES_RU["accumulation"], "score": sc, "details": details}
