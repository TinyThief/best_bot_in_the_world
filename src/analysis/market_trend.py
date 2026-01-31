"""
Определение тренда рынка по OHLCV.

Использует несколько источников:
  - Структура (HH+HL / LH+LL) — свинг-точки
  - EMA-стек (20/50/200) — цена выше/ниже стека
  - ADX и +DI/-DI — сила и направление тренда
  - Сила тренда (доля направленного движения по закрытиям)
  - VWAP — цена выше/ниже объёмно-взвешенной средней
  - OBV slope — давление покупателей/продавцов
  - Return 5/20 — краткосрочный и средний импульс

Возвращает: direction (up/down/flat), strength (0..1), details, trend_unclear, secondary_direction, strength_gap.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core import config
from .market_phases import (
    _adx,
    _atr,
    _bb_width,
    _ema_stack,
    _obv_slope,
    _recent_return,
    _rsi,
    _structure,
    _trend_strength,
    _volume_ratio,
    _vwap_rolling,
)

logger = logging.getLogger(__name__)

TREND_NAMES_RU = {"up": "Вверх", "down": "Вниз", "flat": "Флэт"}
REGIME_NAMES_RU = {"trend": "Тренд", "range": "Диапазон", "surge": "Всплеск"}
MOMENTUM_STATE_RU = {"strong": "Сильный", "fading": "Затухает", "neutral": "Нейтральный"}
MOMENTUM_DIRECTION_RU = {"bullish": "Бычий", "bearish": "Медвежий", "neutral": "Нейтральный"}

# Адаптация по таймфрейму: короткие ТФ — быстрее реакция, длинные — плавнее (меньше шума).
# short: 1,3,5,15,30 мин; long: 60,120,240,D,W,M. Конфиг .env по-прежнему имеет приоритет при явной настройке.
TREND_PROFILES = {
    "short": {"lookback": 80, "min_gap": 0.06, "min_gap_down": 0.05},
    "long": {"lookback": 120, "min_gap": 0.10, "min_gap_down": 0.10},
}


def _tf_to_trend_profile(timeframe: str | None) -> str:
    """Возвращает 'short' или 'long' по строке таймфрейма (как в фазах)."""
    if not timeframe:
        return "long"
    tf = str(timeframe).strip().upper()
    if tf in ("D", "W", "M"):
        return "long"
    try:
        m = int(tf)
        return "short" if m <= 30 else "long"
    except ValueError:
        return "long"


def detect_regime(candles: list[dict[str, Any]], lookback: int = 50) -> dict[str, Any]:
    """
    Режим рынка по ADX, ATR и ширине BB: trend / range / surge.
    trend — выраженный тренд (ADX > 25, ATR не экстремальный).
    range — флэт (ADX < 20).
    surge — всплеск волатильности (ATR >> MA(ATR) или очень широкая BB).
    """
    if not candles or len(candles) < 30:
        return {"regime": "range", "regime_ru": REGIME_NAMES_RU["range"], "adx": None, "atr_ratio": None, "bb_width": None}
    c = candles[-min(lookback, len(candles)):]
    adx_val, _, _ = _adx(c, 14)
    atr_now = _atr(c, 14)
    atr_prev = _atr(c[:-10], 14) if len(c) >= 24 else atr_now
    atr_ratio = (atr_now / atr_prev) if (atr_prev and atr_prev > 0 and atr_now) else 1.0
    bb_w = _bb_width(c, 20, 2.0)
    adx = adx_val if adx_val is not None else 0.0
    if atr_ratio >= 2.0 or (bb_w is not None and bb_w >= 0.15):
        regime = "surge"
    elif adx >= 25 and atr_ratio < 1.8:
        regime = "trend"
    elif adx < 20:
        regime = "range"
    else:
        regime = "trend" if adx >= 22 else "range"
    return {
        "regime": regime,
        "regime_ru": REGIME_NAMES_RU.get(regime, regime),
        "adx": round(adx, 2) if adx_val is not None else None,
        "atr_ratio": round(atr_ratio, 3) if atr_ratio else None,
        "bb_width": round(bb_w, 4) if bb_w is not None else None,
    }


def detect_trend(
    candles: list[dict[str, Any]],
    lookback: int = 100,
    *,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """
    Определяет текущий тренд по последним свечам.

    Агрегирует: структуру, EMA-стек, ADX, силу тренда, VWAP, OBV, return 5/20
    в bullish_score и bearish_score. direction = argmax; strength = нормализованный score.
    trend_unclear = True, если strength ниже порога или разрыв между up/down мал.

    Возвращает:
      direction (up/down/flat), direction_ru, strength (0..1), details,
      trend_unclear, secondary_direction, secondary_direction_ru, secondary_strength, strength_gap.
    """
    strength_min = getattr(config, "TREND_STRENGTH_MIN", 0.35)
    unclear_threshold = getattr(config, "TREND_UNCLEAR_THRESHOLD", 0.3)
    min_gap = getattr(config, "TREND_MIN_GAP", 0.08)
    flat_when_range = getattr(config, "TREND_FLAT_WHEN_RANGE", True)
    min_gap_down = getattr(config, "TREND_MIN_GAP_DOWN", 0.0)

    # Адаптация по таймфрейму: short — мягче (быстрее реакция), long — строже (меньше шума)
    use_profiles = getattr(config, "TREND_USE_PROFILES", True)
    if use_profiles and timeframe:
        prof = TREND_PROFILES.get(_tf_to_trend_profile(timeframe), TREND_PROFILES["long"])
        lookback = prof["lookback"]
        min_gap = prof["min_gap"]
        min_gap_down = prof["min_gap_down"]

    if not candles or len(candles) < 30:
        return _build_trend_result(
            "flat",
            0.0,
            {"reason": "мало данных"},
            strength_min,
            unclear_threshold,
            min_gap,
        )

    lookback_eff = min(lookback, len(candles))
    if len(candles) >= 200:
        lookback_eff = min(max(lookback, 200), len(candles))
    c = candles[-lookback_eff:]

    structure = _structure(c, pivots=5)
    ema_stack = _ema_stack(c)
    adx_val, plus_di, minus_di = _adx(c, 14)
    trend_str = _trend_strength(c, 14)
    vwap_val, vwap_distance = _vwap_rolling(c, min(50, len(c)))
    obv_s = _obv_slope(c, 14) if len(c) >= 15 else None
    ret_5 = _recent_return(c, 5)
    ret_20 = _recent_return(c, min(20, len(c) - 1))

    details = {
        "structure": structure,
        "ema_trend": ema_stack.get("ema_trend"),
        "ema20": round(ema_stack["ema20"], 4) if ema_stack.get("ema20") is not None else None,
        "ema50": round(ema_stack["ema50"], 4) if ema_stack.get("ema50") is not None else None,
        "ema200": round(ema_stack["ema200"], 4) if ema_stack.get("ema200") is not None else None,
        "adx": round(adx_val, 2) if adx_val is not None else None,
        "plus_di": round(plus_di, 2) if plus_di is not None else None,
        "minus_di": round(minus_di, 2) if minus_di is not None else None,
        "trend_strength": round(trend_str, 3) if trend_str is not None else None,
        "vwap_distance": round(vwap_distance, 4) if vwap_distance is not None else None,
        "obv_slope": round(obv_s, 4) if obv_s is not None else None,
        "return_5": round(ret_5, 4) if ret_5 is not None else None,
        "return_20": round(ret_20, 4) if ret_20 is not None else None,
    }
    vol_ratio = _volume_ratio(c, short=5, long=20)
    if vol_ratio is not None:
        details["volume_ratio"] = round(vol_ratio, 3)

    # Накопление бычьих и медвежьих очков (0..1)
    bull = 0.0
    bear = 0.0

    # Структура: up = +0.2 bull, down = +0.2 bear
    if structure == "up":
        bull += 0.2
    elif structure == "down":
        bear += 0.2

    # EMA-стек
    ema_trend = ema_stack.get("ema_trend")
    if ema_trend == "bullish":
        bull += 0.18
    elif ema_trend == "bearish":
        bear += 0.18

    # ADX: сила тренда; +DI/-DI — направление
    adx = adx_val if adx_val is not None else 0.0
    if adx >= 25:
        adx_contrib = min(0.15, (adx - 25) / 50)
        if plus_di is not None and minus_di is not None:
            if plus_di > minus_di:
                bull += 0.12 + adx_contrib
            else:
                bear += 0.12 + adx_contrib
    elif adx >= 15:
        if plus_di is not None and minus_di is not None:
            if plus_di > minus_di:
                bull += 0.06
            else:
                bear += 0.06

    # Сила тренда (направленное движение) — усиленные веса для быстрой реакции на развороты
    ts = trend_str if trend_str is not None else 0.5
    if ret_5 is not None:
        if ret_5 > 0.005:
            bull += 0.10 * min(1.0, ret_5 / 0.02)
        elif ret_5 < -0.005:
            bear += 0.10 * min(1.0, abs(ret_5) / 0.02)
    if ret_20 is not None:
        if ret_20 > 0.01:
            bull += 0.12 * min(1.0, ret_20 / 0.05)
        elif ret_20 < -0.01:
            bear += 0.12 * min(1.0, abs(ret_20) / 0.05)

    # Метрика _trend_strength (доля направленного движения по закрытиям): бонус при согласии с направлением
    if ts > 0.55:
        if structure == "up" or (ret_5 is not None and ret_5 > 0):
            bull += 0.05 * min(1.0, (ts - 0.5) * 2)
        elif structure == "down" or (ret_5 is not None and ret_5 < 0):
            bear += 0.05 * min(1.0, (ts - 0.5) * 2)
    elif ts < 0.35:
        # Слабый тренд — слегка снижаем обе стороны, чаще получится flat
        bull *= 0.95
        bear *= 0.95

    # VWAP: цена выше/ниже
    vd = vwap_distance if vwap_distance is not None else 0.0
    if vd > 0.001:
        bull += 0.1 * min(1.0, vd / 0.02)
    elif vd < -0.001:
        bear += 0.1 * min(1.0, abs(vd) / 0.02)

    # OBV slope
    obv = obv_s if obv_s is not None else 0.0
    if obv > 0.03:
        bull += 0.08 * min(1.0, obv / 0.1)
    elif obv < -0.03:
        bear += 0.08 * min(1.0, abs(obv) / 0.1)

    # Объём: подтверждение тренда — рост объёма на движении усиливает сигнал
    vr = vol_ratio if vol_ratio is not None else 1.0
    if vr >= 1.15:
        bonus = 0.03 * min(1.0, (vr - 1.0) / 0.5)
        if bull > bear:
            bull += bonus
        elif bear > bull:
            bear += bonus

    # Нормализуем суммы в 0..1 (каждая группа уже ограничена по смыслу)
    bull = min(1.0, bull)
    bear = min(1.0, bear)

    # Направление: у кого больше очков и выше порога
    flat_threshold = 0.25
    if bull > bear and bull >= flat_threshold:
        direction = "up"
        strength = bull
        secondary_strength = bear
    elif bear > bull and bear >= flat_threshold:
        # Строже для "вниз": требуем больший разрыв (меньше ложных down)
        gap_down = bear - bull
        if min_gap_down > 0 and gap_down < min_gap_down:
            direction = "flat"
            strength = bear
            secondary_strength = bull
        else:
            direction = "down"
            strength = bear
            secondary_strength = bull
            # Подтверждение «вниз»: хотя бы ADX (+DI/-DI) или структура согласны
            di_bear = plus_di is not None and minus_di is not None and minus_di > plus_di
            struct_bear = structure == "down"
            if not (di_bear or struct_bear):
                direction = "flat"
                strength = max(bull, bear)
                secondary_strength = min(bull, bear)
    else:
        direction = "flat"
        strength = max(bull, bear)
        secondary_strength = min(bull, bear)

    # В боковике (ADX < 20) чаще возвращаем flat, если тренд не очень выражен
    if flat_when_range and adx < 20 and direction in ("up", "down"):
        if strength < 0.5 or (strength - secondary_strength) < 0.12:
            direction = "flat"
            strength = max(bull, bear)
            secondary_strength = min(bull, bear)

    strength = round(strength, 4)
    strength_gap = round(max(0.0, strength - secondary_strength), 4)
    secondary_direction = "down" if direction == "up" else "up" if direction == "down" else ("up" if bull >= bear else "down")
    if direction == "flat":
        secondary_direction = "up" if bull >= bear else "down"

    # Уверенность в выбранном направлении (0..1): доля очков выигравшей стороны.
    # Интерпретация: trend_confidence ≈ «вероятность» этого направления при данной картине (bull vs bear).
    total = bull + bear
    if total > 0:
        trend_confidence = (bull if direction == "up" else bear if direction == "down" else max(bull, bear)) / total
    else:
        trend_confidence = 0.5
    trend_confidence = round(min(1.0, max(0.0, trend_confidence)), 4)

    trend_unclear = (
        strength < unclear_threshold
        or strength < strength_min
        or strength_gap < min_gap
    )

    return {
        "direction": direction,
        "direction_ru": TREND_NAMES_RU.get(direction, direction),
        "strength": strength,
        "trend_confidence": trend_confidence,
        "details": details,
        "trend_unclear": trend_unclear,
        "secondary_direction": secondary_direction,
        "secondary_direction_ru": TREND_NAMES_RU.get(secondary_direction, secondary_direction),
        "secondary_strength": round(secondary_strength, 4),
        "strength_gap": strength_gap,
        "bullish_score": round(bull, 4),
        "bearish_score": round(bear, 4),
    }


def _build_trend_result(
    direction: str,
    strength: float,
    details: dict[str, Any],
    strength_min: float,
    unclear_threshold: float,
    min_gap: float,
) -> dict[str, Any]:
    """Результат тренда при недостатке данных или fallback."""
    return {
        "direction": direction,
        "direction_ru": TREND_NAMES_RU.get(direction, direction),
        "strength": strength,
        "trend_confidence": 0.0,
        "details": details,
        "trend_unclear": True,
        "secondary_direction": None,
        "secondary_direction_ru": None,
        "secondary_strength": 0.0,
        "strength_gap": 0.0,
        "bullish_score": 0.0,
        "bearish_score": 0.0,
    }


def get_trend_name_ru(direction: str) -> str:
    """Русское название тренда по идентификатору."""
    return TREND_NAMES_RU.get(direction, direction)


def detect_momentum(
    candles: list[dict[str, Any]],
    rsi_period: int = 14,
    return_bars: int = 5,
) -> dict[str, Any]:
    """
    Состояние импульса: strong / fading / neutral и направление bullish / bearish / neutral.

    strong — RSI и return_5 совпадают по направлению (RSI > 60 и return_5 > 0 или RSI < 40 и return_5 < 0).
    fading — RSI в экстремуме, но return_5 против (выдох) или RSI в нейтральной зоне 40–60.
    neutral — иначе.

    Возвращает: momentum_state, momentum_state_ru, momentum_direction, momentum_direction_ru, rsi, return_5, details.
    """
    if not candles or len(candles) < max(rsi_period + 1, return_bars + 1):
        return {
            "momentum_state": "neutral",
            "momentum_state_ru": MOMENTUM_STATE_RU["neutral"],
            "momentum_direction": "neutral",
            "momentum_direction_ru": MOMENTUM_DIRECTION_RU["neutral"],
            "rsi": None,
            "return_5": None,
            "details": {"reason": "мало данных"},
        }
    c = candles[-min(50, len(candles)):]
    rsi_val = _rsi(c, rsi_period)
    ret = _recent_return(c, return_bars)
    rsi_val = rsi_val if rsi_val is not None else 50.0
    ret = ret if ret is not None else 0.0

    if rsi_val > 55 and ret > 0.005:
        direction = "bullish"
    elif rsi_val < 45 and ret < -0.005:
        direction = "bearish"
    else:
        direction = "neutral"

    if rsi_val > 65 and ret > 0.01:
        state = "strong"
    elif rsi_val < 35 and ret < -0.01:
        state = "strong"
    elif (rsi_val > 60 and ret < -0.005) or (rsi_val < 40 and ret > 0.005):
        state = "fading"
    elif 40 <= rsi_val <= 60:
        state = "neutral"
    else:
        state = "strong" if (rsi_val > 60 and ret > 0) or (rsi_val < 40 and ret < 0) else "neutral"

    return {
        "momentum_state": state,
        "momentum_state_ru": MOMENTUM_STATE_RU.get(state, state),
        "momentum_direction": direction,
        "momentum_direction_ru": MOMENTUM_DIRECTION_RU.get(direction, direction),
        "rsi": round(rsi_val, 2),
        "return_5": round(ret, 4),
        "details": {"rsi": rsi_val, "return_5": ret},
    }
