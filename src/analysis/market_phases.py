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
        "vol_spike": 1.5,
        "drop_threshold": -0.07,
        "range_position_low": 0.35,
        "range_position_high": 0.70,
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


def _ema_stack(
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    EMA 20 / 50 / 200 по закрытиям и признак тренда по стеку.

    Возвращает: ema20, ema50, ema200, ema_trend.
    ema_trend: 'bullish' (цена > EMA20 > EMA50 > EMA200), 'bearish' (обратно), 'mixed'.
    """
    if not candles or len(candles) < 200:
        return {"ema20": None, "ema50": None, "ema200": None, "ema_trend": None}
    closes = [c["close"] for c in candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    if ema20 is None or ema50 is None or ema200 is None:
        return {"ema20": ema20, "ema50": ema50, "ema200": ema200, "ema_trend": None}
    last = closes[-1]
    if last > ema20 > ema50 > ema200:
        trend = "bullish"
    elif last < ema20 < ema50 < ema200:
        trend = "bearish"
    else:
        trend = "mixed"
    return {"ema20": ema20, "ema50": ema50, "ema200": ema200, "ema_trend": trend}


def _atr(candles: list[dict[str, Any]], length: int = 14) -> float | None:
    """ATR за последние length свечей (упрощённо: true range = high - low)."""
    if not candles or len(candles) < length:
        return None
    recent = candles[-length:]
    trs = [c["high"] - c["low"] for c in recent]
    return sum(trs) / len(trs)


def _adx(
    candles: list[dict[str, Any]], period: int = 14
) -> tuple[float | None, float | None, float | None]:
    """
    ADX(period), +DI и -DI по Уайлдеру.

    Возвращает (adx, plus_di, minus_di). Нужно не менее 2*period+1 свечей.
    """
    if not candles or len(candles) < 2 * period + 1:
        return None, None, None
    # TR, +DM, -DM по каждой свече (начиная со 2-й)
    tr_list: list[float] = []
    plus_dm_list: list[float] = []
    minus_dm_list: list[float] = []
    for i in range(1, len(candles)):
        h, l_ = candles[i]["high"], candles[i]["low"]
        prev_h, prev_l = candles[i - 1]["high"], candles[i - 1]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(h - l_, abs(h - prev_close), abs(l_ - prev_close))
        up_move = h - prev_h
        down_move = prev_l - l_
        plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0
        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
    # Сглаживание Уайлдера с начала ряда
    def wilder_smooth(series: list[float]) -> list[float]:
        if len(series) < period:
            return []
        sm = sum(series[:period]) / period
        out = [sm]
        for i in range(period, len(series)):
            sm = (sm * (period - 1) + series[i]) / period
            out.append(sm)
        return out

    tr_smooth = wilder_smooth(tr_list)
    plus_dm_smooth = wilder_smooth(plus_dm_list)
    minus_dm_smooth = wilder_smooth(minus_dm_list)
    if len(tr_smooth) < period + 1:
        return None, None, None
    # +DI, -DI, затем DX
    plus_di_list = [
        100.0 * plus_dm_smooth[i] / tr_smooth[i] if tr_smooth[i] > 0 else 0.0
        for i in range(len(tr_smooth))
    ]
    minus_di_list = [
        100.0 * minus_dm_smooth[i] / tr_smooth[i] if tr_smooth[i] > 0 else 0.0
        for i in range(len(tr_smooth))
    ]
    dx_list = [
        100.0 * abs(plus_di_list[i] - minus_di_list[i]) / (plus_di_list[i] + minus_di_list[i])
        if (plus_di_list[i] + minus_di_list[i]) > 0
        else 0.0
        for i in range(len(plus_di_list))
    ]
    adx_series = wilder_smooth(dx_list)
    if not adx_series:
        return None, None, None
    return adx_series[-1], plus_di_list[-1], minus_di_list[-1]


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


def _bb_width(
    candles: list[dict[str, Any]], period: int = 20, mult: float = 2.0
) -> float | None:
    """
    Ширина полос Боллинджера: (upper - lower) / middle.

    middle = SMA(period), upper/lower = middle ± mult*std(close).
    Низкая ширина — сжатие (squeeze), высокая — расширение. Нужно не менее period свечей.
    """
    if not candles or len(candles) < period:
        return None
    closes = [c["close"] for c in candles[-period:]]
    middle = sum(closes) / period
    variance = sum((x - middle) ** 2 for x in closes) / period
    if variance <= 0:
        return 0.0
    std = variance ** 0.5
    upper = middle + mult * std
    lower = middle - mult * std
    if middle <= 0:
        return None
    return (upper - lower) / middle


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


def _obv(candles: list[dict[str, Any]]) -> float | None:
    """On-Balance Volume: накопленный объём с учётом направления (close > prev → +vol, иначе −vol)."""
    if not candles or len(candles) < 2:
        return None
    obv = 0.0
    for i in range(1, len(candles)):
        if candles[i]["close"] > candles[i - 1]["close"]:
            obv += candles[i]["volume"]
        elif candles[i]["close"] < candles[i - 1]["close"]:
            obv -= candles[i]["volume"]
    return obv


def _obv_slope(
    candles: list[dict[str, Any]], lookback: int = 14
) -> float | None:
    """
    Наклон OBV за lookback свечей: (OBV_end - OBV_start) / |OBV_start| или нормализованный.

    > 0 — давление покупателей, < 0 — продавцов. None при недостатке данных.
    """
    if not candles or len(candles) < lookback + 1:
        return None
    # OBV на момент (end - lookback) и на конец
    obv_start = _obv(candles[: -lookback])
    obv_end = _obv(candles)
    if obv_start is None or obv_end is None:
        return None
    diff = obv_end - obv_start
    if obv_start == 0:
        return 1.0 if diff > 0 else (-1.0 if diff < 0 else 0.0)
    return diff / abs(obv_start)


def _vwap_rolling(
    candles: list[dict[str, Any]], lookback: int | None = None
) -> tuple[float | None, float | None]:
    """
    Rolling VWAP за последние lookback свечей: sum(typical_price * volume) / sum(volume).

    typical_price = (high + low + close) / 3.
    Возвращает (vwap, distance): distance = (close - vwap) / vwap — доля выше/ниже VWAP.
    Для 24/7 без сессий — единственный вариант. lookback=None — все свечи.
    """
    if not candles:
        return None, None
    use = candles[-lookback:] if lookback else candles
    if not use:
        return None, None
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for c in use:
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        vol = c["volume"]
        cum_tp_vol += tp * vol
        cum_vol += vol
    if cum_vol <= 0:
        return None, None
    vwap = cum_tp_vol / cum_vol
    last_close = use[-1]["close"]
    if vwap <= 0:
        return vwap, None
    distance = (last_close - vwap) / vwap
    return vwap, distance


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


def _spring_upthrust_volume_confirmed(
    candles: list[dict[str, Any]], lookback: int = 30, tail: int = 10, break_pct: float = 0.002, vol_mult: float = 1.2
) -> tuple[bool, bool, bool, bool]:
    """
    Spring/upthrust плюс подтверждение объёмом: в окне tail был бар с объёмом > vol_mult * ср. объём.

    Возвращает (spring, upthrust, spring_vol_ok, upthrust_vol_ok).
    spring_vol_ok: spring и в tail есть бар с объёмом выше среднего (подтверждение капитуляции/накопления).
    """
    spring, upthrust = _spring_upthrust(candles, lookback=lookback, tail=tail, break_pct=break_pct)
    if not candles or len(candles) < lookback or lookback <= tail:
        return spring, upthrust, False, False
    last = candles[-tail:]
    avg_vol = sum(c["volume"] for c in last) / len(last)
    if avg_vol <= 0:
        return spring, upthrust, False, False
    # Бар с пробоем низа (low минимальный в tail) или верха (high максимальный в tail) с повышенным объёмом
    max_vol = max(c["volume"] for c in last)
    vol_ok = max_vol >= vol_mult * avg_vol
    return spring, upthrust, spring and vol_ok, upthrust and vol_ok


def _climax(
    candles: list[dict[str, Any]],
    ret_bars: int = 5,
    vol_short: int = 3,
    vol_long: int = 20,
    ret_threshold: float = 0.03,
    vol_spike: float = 1.5,
) -> tuple[bool, bool]:
    """
    Selling climax (капитуляция продавцов) и Buying climax (истощение покупателей) по Вайкоффу.

    Selling: резкое падение (ret_5 < -ret_threshold) + всплеск объёма (vol_ratio >= vol_spike).
    Buying: резкий рост (ret_5 > ret_threshold) + всплеск объёма.
    Возвращает (selling_climax, buying_climax).
    """
    if not candles or len(candles) < max(ret_bars + 1, vol_long):
        return False, False
    ret = _recent_return(candles, ret_bars)
    vol_ratio = _volume_ratio(candles, short=vol_short, long=vol_long)
    if ret is None or vol_ratio is None:
        return False, False
    selling = ret <= -ret_threshold and vol_ratio >= vol_spike
    buying = ret >= ret_threshold and vol_ratio >= vol_spike
    return selling, buying


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

    def in_low(seq: list[dict[str, Any]]) -> int:
        return sum(1 for c in seq if c["close"] <= low_bound)

    def in_high(seq: list[dict[str, Any]]) -> int:
        return sum(1 for c in seq if c["close"] >= high_bound)

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

    # При наличии 200+ свечей используем окно 200 для EMA200 и более полной структуры
    lookback_eff = lookback
    if len(candles) >= 200:
        lookback_eff = min(max(lookback, 200), len(candles))
    c = candles[-lookback_eff:] if len(candles) >= lookback_eff else candles
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
    spring_vol, upthrust_vol = False, False
    if len(c) >= 20:
        _, _, spring_vol, upthrust_vol = _spring_upthrust_volume_confirmed(
            c, lookback=min(30, len(c)), tail=min(10, len(c) // 3)
        )
    selling_climax, buying_climax = _climax(c, ret_bars=5, vol_spike=1.5)
    trend_strength = _trend_strength(c, 14)
    fresh_low, fresh_high = _zone_freshness(c, lookback=min(20, len(c)), band=0.2)
    # Новые метрики: EMA-стек, ADX, BB width, OBV, VWAP
    ema_stack = _ema_stack(c)
    adx_val, plus_di, minus_di = _adx(c, 14)
    bb_width = _bb_width(c, 20, 2.0)
    obv_slope = _obv_slope(c, 14) if len(c) >= 15 else None
    vwap_val, vwap_distance = _vwap_rolling(c, min(50, len(c)))

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
        "spring_volume_confirmed": spring_vol,
        "upthrust_volume_confirmed": upthrust_vol,
        "selling_climax": selling_climax,
        "buying_climax": buying_climax,
        "trend_strength": round(trend_strength, 3) if trend_strength is not None else None,
        "fresh_low": fresh_low,
        "fresh_high": fresh_high,
        "atr_ratio": round(atr_ratio, 3) if atr_ratio else None,
        "return_5": round(ret_5, 4) if ret_5 is not None else None,
        "return_20": round(ret_20, 4) if ret_20 is not None else None,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "ema20": round(ema_stack["ema20"], 4) if ema_stack.get("ema20") is not None else None,
        "ema50": round(ema_stack["ema50"], 4) if ema_stack.get("ema50") is not None else None,
        "ema200": round(ema_stack["ema200"], 4) if ema_stack.get("ema200") is not None else None,
        "ema_trend": ema_stack.get("ema_trend"),
        "adx": round(adx_val, 2) if adx_val is not None else None,
        "plus_di": round(plus_di, 2) if plus_di is not None else None,
        "minus_di": round(minus_di, 2) if minus_di is not None else None,
        "bb_width": round(bb_width, 4) if bb_width is not None else None,
        "obv_slope": round(obv_slope, 4) if obv_slope is not None else None,
        "vwap": round(vwap_val, 4) if vwap_val is not None else None,
        "vwap_distance": round(vwap_distance, 4) if vwap_distance is not None else None,
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
    ema_trend = ema_stack.get("ema_trend")
    adx = adx_val if adx_val is not None else 0.0
    bb_w = bb_width if bb_width is not None else 0.05
    obv_s = obv_slope if obv_slope is not None else 0.0
    vwap_dist = vwap_distance if vwap_distance is not None else 0.0

    if r5 <= drop_threshold and vol >= vol_spike:
        sc = min(1.0, abs(r5) * 5 + (vol - 1) * 0.2)
        if rsi_val < 30:
            sc = _clip_score(sc + 0.05)
        if selling_climax:
            sc = _clip_score(sc + 0.06)
        if spring_vol:
            sc = _clip_score(sc + 0.03)
        sc = _apply_higher_tf_context("capitulation", sc, higher_tf_phase, higher_tf_trend)
        return {"phase": "capitulation", "phase_ru": PHASE_NAMES_RU["capitulation"], "score": sc, "details": details}

    if r5 is not None and r20 is not None and r5 > 0.01 and r20 < -0.02:
        strength = min(1.0, (r5 - 0.01) / 0.02) * 0.5 + min(1.0, abs(r20) / 0.05) * 0.3
        sc = _clip_score(0.55 + strength)
        if rsi_val < 35:
            sc = _clip_score(sc + 0.08)
        if rsi_bull_div:
            sc = _clip_score(sc + 0.05)
        if ema_trend == "bullish" or vwap_dist > 0:
            sc = _clip_score(sc + 0.02)
        if obv_s > 0.05:
            sc = _clip_score(sc + 0.02)
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
        confirm_bull = sum([ema_trend == "bullish", adx > 25, vwap_dist > 0, obv_s > 0.05])
        if confirm_bull >= 3:
            sc = _clip_score(sc + 0.08)
        elif confirm_bull >= 2:
            sc = _clip_score(sc + 0.05)
        else:
            if ema_trend == "bullish":
                sc = _clip_score(sc + 0.03)
            if adx > 25:
                sc = _clip_score(sc + 0.02)
            if obv_s > 0.05:
                sc = _clip_score(sc + 0.02)
            if vwap_dist > 0:
                sc = _clip_score(sc + 0.02)
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
        confirm_bear = sum([ema_trend == "bearish", adx > 25, vwap_dist < 0, obv_s < -0.05])
        if confirm_bear >= 3:
            sc = _clip_score(sc + 0.08)
        elif confirm_bear >= 2:
            sc = _clip_score(sc + 0.05)
        else:
            if ema_trend == "bearish":
                sc = _clip_score(sc + 0.03)
            if adx > 25:
                sc = _clip_score(sc + 0.02)
            if obv_s < -0.05:
                sc = _clip_score(sc + 0.02)
            if vwap_dist < 0:
                sc = _clip_score(sc + 0.02)
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
            if spring_vol:
                sc = _clip_score(sc + 0.03)
            if trend_str < 0.3:
                sc = _clip_score(sc + 0.03)
            if fresh_low:
                sc = _clip_score(sc + 0.02)
            if adx < 20:
                sc = _clip_score(sc + 0.02)
            if bb_w < 0.04:
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
            if upthrust_vol:
                sc = _clip_score(sc + 0.03)
            if buying_climax:
                sc = _clip_score(sc + 0.05)
            if trend_str < 0.3:
                sc = _clip_score(sc + 0.03)
            if fresh_high:
                sc = _clip_score(sc + 0.02)
            if adx < 20:
                sc = _clip_score(sc + 0.02)
            if bb_w < 0.04:
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
