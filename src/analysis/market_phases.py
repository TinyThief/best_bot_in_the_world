"""
Определение 6 фаз рынка по OHLCV.

Фазы (Wyckoff-подобная схема + капитуляция и восстановление):
  1. ACCUMULATION   — накопление у низа, боковик, низкая волатильность
  2. MARKUP        — восходящий тренд
  3. DISTRIBUTION  — распределение у верха, боковик или разворот вниз
  4. MARKDOWN      — нисходящий тренд
  5. CAPITULATION  — капитуляция: резкое падение и/или всплеск объёма (часто дно, ожидаем отскок)
  6. RECOVERY      — восстановление: отскок от дна, стабилизация после капитуляции

Для интерпретации в стратегиях и бэктесте:
  BULLISH_PHASES   — фазы, после которых обычно рост (markup, recovery, capitulation)
  BEARISH_PHASES   — фазы, после которых обычно падение (markdown, distribution)
  accumulation     — нейтральная
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Идентификаторы и русские названия фаз
PHASES = (
    "accumulation",   # накопление
    "markup",         # рост
    "distribution",   # распределение
    "markdown",       # падение
    "capitulation",   # капитуляция (по смыслу — зона дна, ожидаем отскок)
    "recovery",       # восстановление
)
PHASE_NAMES_RU = {
    "accumulation": "Накопление",
    "markup": "Рост",
    "distribution": "Распределение",
    "markdown": "Падение",
    "capitulation": "Капитуляция",
    "recovery": "Восстановление",
}

# Для метрик «точность по направлению»: капитуляция = ожидаем отскок (считаем бычьей)
BULLISH_PHASES = {"markup", "recovery", "capitulation"}
BEARISH_PHASES = {"markdown", "distribution"}

# Профили порогов по таймфрейму (короткий ТФ — больше шума, длинный — плавнее)
# Ключи: "short" (1,3,5,15,30), "long" (60,120,240,D,W,M)
PHASE_PROFILES = {
    "short": {
        "vol_spike": 2.0,
        "drop_threshold": -0.04,
        "range_position_low": 0.30,
        "range_position_high": 0.70,
    },
    "long": {
        "vol_spike": 1.6,
        "drop_threshold": -0.06,
        "range_position_low": 0.35,
        "range_position_high": 0.65,
    },
}


def _tf_to_profile(timeframe: str) -> str:
    """Возвращает 'short' или 'long' по строке таймфрейма."""
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


def _ema(series: list[float], length: int) -> float | None:
    """Экспоненциальная скользящая по последним значениям. Последнее значение EMA."""
    if not series or len(series) < length:
        return None
    k = 2.0 / (length + 1)
    ema_val = sum(series[:length]) / length
    for i in range(length, len(series)):
        ema_val = series[i] * k + ema_val * (1 - k)
    return ema_val


def _atr(candles: list[dict[str, Any]], length: int = 14) -> float | None:
    """ATR за последние length свечей (упрощённо: true range = high - low)."""
    if not candles or len(candles) < length:
        return None
    recent = candles[-length:]
    trs = [c["high"] - c["low"] for c in recent]
    return sum(trs) / len(trs)


def _price_position_in_range(candles: list[dict[str, Any]], lookback: int) -> float | None:
    """Позиция цены закрытия в диапазоне [low, high] за lookback свечей. 0 = у низа, 1 = у верха."""
    if not candles or len(candles) < lookback:
        return None
    recent = candles[-lookback:]
    lows = [c["low"] for c in recent]
    highs = [c["high"] for c in recent]
    last_close = recent[-1]["close"]
    r_min, r_max = min(lows), max(highs)
    if r_max <= r_min:
        return 0.5
    return (last_close - r_min) / (r_max - r_min)


def _volume_ratio(candles: list[dict[str, Any]], short: int = 3, long: int = 20) -> float | None:
    """Отношение среднего объёма за short последних свечей к среднему за long."""
    if not candles or len(candles) < long:
        return None
    vols = [c["volume"] for c in candles]
    avg_short = sum(vols[-short:]) / short
    avg_long = sum(vols[-long:]) / long
    if avg_long <= 0:
        return None
    return avg_short / avg_long


def _volume_at_range_bounds(
    candles: list[dict[str, Any]], lookback: int = 50, band: float = 0.15
) -> tuple[float | None, float | None]:
    """
    Отношение среднего объёма у границ диапазона к среднему объёму по всем свечам.

    band — доля диапазона (0.15 = нижние/верхние 15% по цене).
    Возвращает (ratio_at_low, ratio_at_high):
      ratio_at_low  > 1 — у низа объём выше среднего (подтверждение accumulation)
      ratio_at_high > 1 — у верха объём выше среднего (подтверждение distribution)
    """
    if not candles or len(candles) < lookback:
        return None, None
    recent = candles[-lookback:]
    lows = [c["low"] for c in recent]
    highs = [c["high"] for c in recent]
    r_min, r_max = min(lows), max(highs)
    if r_max <= r_min:
        return None, None
    span = r_max - r_min
    low_bound = r_min + band * span
    high_bound = r_max - band * span
    vols = [c["volume"] for c in recent]
    avg_all = sum(vols) / len(vols)
    if avg_all <= 0:
        return None, None
    at_low = [c["volume"] for c in recent if c["low"] <= low_bound]
    at_high = [c["volume"] for c in recent if c["high"] >= high_bound]
    ratio_low = (sum(at_low) / len(at_low)) / avg_all if at_low else None
    ratio_high = (sum(at_high) / len(at_high)) / avg_all if at_high else None
    return ratio_low, ratio_high


def _volume_pressure_at_bounds(
    candles: list[dict[str, Any]], lookback: int = 50, band: float = 0.15
) -> tuple[float | None, float | None]:
    """
    «Давление» объёма у границ: кто активнее — покупатели у низа, продавцы у верха.

    Возвращает (buying_pressure_low, selling_pressure_high):
      buying_pressure_low  = (ср. объём бычьих свечей в нижней band) / (ср. объём медвежьих там).
        > 1 — у низа больше объёма на росте (подтверждение accumulation).
      selling_pressure_high = (ср. объём медвежьих в верхней band) / (ср. объём бычьих там).
        > 1 — у верха больше объёма на падении (подтверждение distribution).
    """
    if not candles or len(candles) < lookback:
        return None, None
    recent = candles[-lookback:]
    lows = [c["low"] for c in recent]
    highs = [c["high"] for c in recent]
    r_min, r_max = min(lows), max(highs)
    if r_max <= r_min:
        return None, None
    span = r_max - r_min
    low_bound = r_min + band * span
    high_bound = r_max - band * span

    vol_bull_low = [c["volume"] for c in recent if c["low"] <= low_bound and c["close"] > c["open"]]
    vol_bear_low = [c["volume"] for c in recent if c["low"] <= low_bound and c["close"] <= c["open"]]
    vol_bull_high = [c["volume"] for c in recent if c["high"] >= high_bound and c["close"] > c["open"]]
    vol_bear_high = [c["volume"] for c in recent if c["high"] >= high_bound and c["close"] <= c["open"]]

    buying = None
    if vol_bear_low and sum(vol_bear_low) > 0 and vol_bull_low:
        avg_bull = sum(vol_bull_low) / len(vol_bull_low)
        avg_bear = sum(vol_bear_low) / len(vol_bear_low)
        buying = avg_bull / avg_bear if avg_bear > 0 else None
    selling = None
    if vol_bull_high and sum(vol_bull_high) > 0 and vol_bear_high:
        avg_bear = sum(vol_bear_high) / len(vol_bear_high)
        avg_bull = sum(vol_bull_high) / len(vol_bull_high)
        selling = avg_bear / avg_bull if avg_bull > 0 else None
    return buying, selling


def _spring_upthrust(
    candles: list[dict[str, Any]], lookback: int = 30, tail: int = 10, break_pct: float = 0.002
) -> tuple[bool, bool]:
    """
    Spring (ложный пробой низа) и Upthrust (ложный пробой верха) диапазона.

    Диапазон — по первым (lookback - tail) барам. В последних tail барах ищем пробой:
    spring  = был low ниже низа диапазона, закрытие последней свечи вернулось внутрь.
    upthrust = был high выше верха диапазона, закрытие вернулось внутрь.
    break_pct — минимальный выход за границу в долях от ширины диапазона.
    Возвращает (spring, upthrust).
    """
    if not candles or len(candles) < lookback or lookback <= tail:
        return False, False
    base = candles[-lookback : -tail]
    last = candles[-tail:]
    if not base or not last:
        return False, False
    r_min = min(c["low"] for c in base)
    r_max = max(c["high"] for c in base)
    span = r_max - r_min
    if span <= 0:
        return False, False
    margin = break_pct * span
    last_min_low = min(c["low"] for c in last)
    last_max_high = max(c["high"] for c in last)
    close = candles[-1]["close"]
    spring = last_min_low <= r_min - margin and r_min <= close <= r_max
    upthrust = last_max_high >= r_max + margin and r_min <= close <= r_max
    return spring, upthrust


def _zone_freshness(
    candles: list[dict[str, Any]], lookback: int = 20, band: float = 0.2
) -> tuple[bool, bool]:
    """
    «Свежесть» входа в зону у границ: недавно пришли в низ/вверх.

    Считаем по закрытиям долю баров в нижней/верхней band диапазона за lookback.
    fresh_low: среди последних 3 баров минимум 2 в нижней зоне, среди баров -6:-3 не более 1.
    fresh_high: аналогично для верха.
    Возвращает (fresh_low, fresh_high).
    """
    if not candles or len(candles) < lookback or lookback < 8:
        return False, False
    recent = candles[-lookback:]
    r_min = min(c["low"] for c in recent)
    r_max = max(c["high"] for c in recent)
    if r_max <= r_min:
        return False, False
    low_bound = r_min + band * (r_max - r_min)
    high_bound = r_max - band * (r_max - r_min)
    last_3 = candles[-3:]
    prev_3 = candles[-6:-3]
    in_low = lambda seq: sum(1 for c in seq if c["close"] <= low_bound)
    in_high = lambda seq: sum(1 for c in seq if c["close"] >= high_bound)
    fresh_low = in_low(last_3) >= 2 and in_low(prev_3) <= 1
    fresh_high = in_high(last_3) >= 2 and in_high(prev_3) <= 1
    return fresh_low, fresh_high


def _structure(candles: list[dict[str, Any]], pivots: int = 5) -> str:
    """Структура: 'up' (HH+HL), 'down' (LH+LL), 'range'."""
    if not candles or len(candles) < pivots * 2:
        return "range"
    closes = [c["close"] for c in candles]
    lows = [c["low"] for c in candles]
    highs = [c["high"] for c in candles]
    step = max(1, len(closes) // pivots)
    last_lows = [min(lows[i : i + step]) for i in range(0, len(lows) - step + 1, step)][-pivots:]
    last_highs = [max(highs[i : i + step]) for i in range(0, len(highs) - step + 1, step)][-pivots:]
    if not last_lows or not last_highs:
        return "range"
    hl_up = all(last_lows[i] >= last_lows[i - 1] * 0.998 for i in range(1, len(last_lows)))
    hl_down = all(last_lows[i] <= last_lows[i - 1] * 1.002 for i in range(1, len(last_lows)))
    hh_up = all(last_highs[i] >= last_highs[i - 1] * 0.998 for i in range(1, len(last_highs)))
    hh_down = all(last_highs[i] <= last_highs[i - 1] * 1.002 for i in range(1, len(last_highs)))
    if hl_up and hh_up:
        return "up"
    if hl_down and hh_down:
        return "down"
    return "range"


def _trend_strength(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    """
    Сила тренда за последние period баров (упрощённый аналог ADX по направлению).

    Суммируем движения вверх и вниз по закрытиям; доля |up - down| / (up + down) даёт 0..1.
    Высокое значение — выраженный тренд, низкое — флэт. None при недостатке данных.
    """
    if not candles or len(candles) < period + 1:
        return None
    closes = [c["close"] for c in candles[-period - 1 :]]
    up = sum(max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    down = sum(max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes)))
    total = up + down
    if total <= 0:
        return 0.0
    return abs(up - down) / total


def _recent_return(candles: list[dict[str, Any]], bars: int = 5) -> float | None:
    """Относительное изменение цены за последние bars свечей (в долях, не %)."""
    if not candles or len(candles) < bars + 1:
        return None
    old_close = candles[-bars - 1]["close"]
    new_close = candles[-1]["close"]
    if old_close <= 0:
        return None
    return (new_close - old_close) / old_close


def _rsi(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    """RSI (0..100) по закрытиям за последние period+1 свечей. None если данных мало."""
    if not candles or len(candles) < period + 1:
        return None
    closes = [c["close"] for c in candles]
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(ch if ch > 0 else 0.0)
        losses.append(-ch if ch < 0 else 0.0)
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _rsi_divergence(
    candles: list[dict[str, Any]], period: int = 14, window: int = 20
) -> tuple[bool, bool]:
    """
    Упрощённая дивергенция RSI по двум половинкам окна (предыдущая и текущая).

    Бычья: цена дала lower low (мин. за текущее полуокно < минимума за предыдущее),
           а RSI — higher low (RSI на текущем полуокне > RSI на предыдущем).
    Медвежья: цена — higher high, RSI — lower high.
    Возвращает (bullish_div, bearish_div). При недостатке данных — (False, False).
    """
    if not candles or len(candles) < 2 * window or 2 * window < period + 2:
        return False, False
    prev = candles[-2 * window : -window]
    recent = candles[-window:]
    if len(prev) < period + 1 or len(recent) < period + 1:
        return False, False
    low_prev = min(c["low"] for c in prev)
    low_recent = min(c["low"] for c in recent)
    high_prev = max(c["high"] for c in prev)
    high_recent = max(c["high"] for c in recent)
    rsi_prev = _rsi(prev, period)
    rsi_recent = _rsi(recent, period)
    if rsi_prev is None or rsi_recent is None:
        return False, False
    bullish = low_recent < low_prev and rsi_recent > rsi_prev
    bearish = high_recent > high_prev and rsi_recent < rsi_prev
    return bullish, bearish


def _clip_score(x: float) -> float:
    """Ограничение score в [0, 1]."""
    return min(1.0, max(0.0, x))


def _apply_higher_tf_context(
    phase: str,
    score: float,
    higher_tf_phase: str | None,
    higher_tf_trend: str | None,
) -> float:
    """Корректирует score с учётом контекста старшего ТФ: +0.04 при согласии, −0.04 при противоречии."""
    if higher_tf_phase is None and higher_tf_trend is None:
        return score
    if phase in BULLISH_PHASES:
        agree = (higher_tf_phase in BULLISH_PHASES) or (higher_tf_trend == "up")
        disagree = (higher_tf_phase in BEARISH_PHASES) or (higher_tf_trend == "down")
    elif phase in BEARISH_PHASES:
        agree = (higher_tf_phase in BEARISH_PHASES) or (higher_tf_trend == "down")
        disagree = (higher_tf_phase in BULLISH_PHASES) or (higher_tf_trend == "up")
    else:
        return score  # accumulation — не меняем
    if agree:
        return _clip_score(score + 0.04)
    if disagree:
        return _clip_score(score - 0.04)
    return score


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
    Определяет текущую фазу рынка по последним свечам.

    Если задан timeframe, используются профили порогов для короткого/длинного ТФ.
    score считается динамически: чем сильнее сигнал (тренд, отскок, позиция в диапазоне),
    тем выше score (до 0.85 для чётких markup/markdown/recovery). Слабые случаи — 0.3–0.5.
    Порог PHASE_SCORE_MIN в конфиге можно ставить 0.7–0.8 для отсечки слабых фаз.

    Возвращает:
      phase, phase_ru, score (0..1), details
    """
    # Дефолты: универсальные или из профиля по ТФ
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
            "details": {"reason": "мало данных"},
        }

    c = candles[-lookback:] if len(candles) >= lookback else candles
    structure = _structure(c, pivots=5)
    position = _price_position_in_range(c, lookback=min(50, len(c)))
    vol_ratio = _volume_ratio(c, short=3, long=20)
    atr_val = _atr(c, 14)
    atr_prev = _atr(c[:-10], 14) if len(c) >= 24 else atr_val
    atr_ratio = (atr_val / atr_prev) if (atr_prev and atr_prev > 0) else 1.0
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
        "atr_ratio": round(atr_ratio, 3) if atr_ratio else None,
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

    if r5 <= drop_threshold and vol >= vol_spike:
        sc = min(1.0, abs(r5) * 5 + (vol - 1) * 0.2)
        if rsi_val < 30:
            sc = _clip_score(sc + 0.05)
        sc = _apply_higher_tf_context("capitulation", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "capitulation", "phase_ru": PHASE_NAMES_RU["capitulation"], "score": sc, "details": details}

    if r5 is not None and r20 is not None and r5 > 0.01 and r20 < -0.02:
        strength = min(1.0, (r5 - 0.01) / 0.02) * 0.5 + min(1.0, abs(r20) / 0.05) * 0.3
        sc = _clip_score(0.55 + strength)
        if rsi_val < 35:
            sc = _clip_score(sc + 0.08)
        if rsi_bull_div:
            sc = _clip_score(sc + 0.05)
        sc = _apply_higher_tf_context("recovery", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "recovery", "phase_ru": PHASE_NAMES_RU["recovery"], "score": sc, "details": details}

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

    if structure == "range":
        if position is not None and pos <= range_position_low:
            # Чем ближе к низу диапазона, тем увереннее accumulation
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


def get_phase_name_ru(phase: str) -> str:
    """Русское название фазы по идентификатору."""
    return PHASE_NAMES_RU.get(phase, phase)
