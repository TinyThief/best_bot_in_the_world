"""
Торговые зоны: динамические уровни поддержки/сопротивления с переключением ролей.

Уровень, образованный как сопротивление (свинг-хай), после пробоя вверх становится поддержкой.
Уровень, образованный как поддержка (свинг-лоу), после пробоя вниз становится сопротивлением.

Улучшения (проп-стиль): объём на уровне, ширина зоны ±ATR, круглые числа, свежесть (decay),
composite strength.
"""
from __future__ import annotations

import logging
from typing import Any

from .market_phases import _atr

logger = logging.getLogger(__name__)

# Роли уровня
ORIGIN_SUPPORT = "support"
ORIGIN_RESISTANCE = "resistance"
CURRENT_SUPPORT = "support"
CURRENT_RESISTANCE = "resistance"


def _find_pivot_lows(
    candles: list[dict[str, Any]], left_bars: int = 3, right_bars: int = 3
) -> list[tuple[float, int]]:
    """
    Локальные минимумы (свинг-лоу): low[i] не больше соседей в окне [i-left_bars, i+right_bars].
    Возвращает список (price, bar_index).
    """
    if not candles or len(candles) < left_bars + right_bars + 1:
        return []
    lows = [c["low"] for c in candles]
    result: list[tuple[float, int]] = []
    for i in range(left_bars, len(lows) - right_bars):
        window_low = min(lows[i - left_bars : i + right_bars + 1])
        if lows[i] <= window_low:
            result.append((lows[i], i))
    return result


def _find_pivot_highs(
    candles: list[dict[str, Any]], left_bars: int = 3, right_bars: int = 3
) -> list[tuple[float, int]]:
    """
    Локальные максимумы (свинг-хай): high[i] не меньше соседей в окне.
    Возвращает список (price, bar_index).
    """
    if not candles or len(candles) < left_bars + right_bars + 1:
        return []
    highs = [c["high"] for c in candles]
    result: list[tuple[float, int]] = []
    for i in range(left_bars, len(highs) - right_bars):
        window_high = max(highs[i - left_bars : i + right_bars + 1])
        if highs[i] >= window_high:
            result.append((highs[i], i))
    return result


def _cluster_levels(
    levels_with_origin: list[tuple[float, int, str]],
    threshold_pct: float,
) -> list[dict[str, Any]]:
    """
    Объединяет уровни, близкие по цене (в пределах threshold_pct от медианы кластера).
    levels_with_origin: (price, bar_index, origin_role).
    Возвращает список уровней: price (медиана кластера), bar_index (последний в кластере),
    origin_role, touches (число уровней в кластере).
    """
    if not levels_with_origin:
        return []
    # Сортируем по цене для группировки
    sorted_levels = sorted(levels_with_origin, key=lambda x: x[0])
    clusters: list[list[tuple[float, int, str]]] = []
    current = [sorted_levels[0]]

    for i in range(1, len(sorted_levels)):
        price, bar_idx, role = sorted_levels[i]
        ref_price = current[0][0]
        if ref_price <= 0:
            current.append((price, bar_idx, role))
            continue
        if abs(price - ref_price) / ref_price <= threshold_pct:
            current.append((price, bar_idx, role))
        else:
            clusters.append(current)
            current = [(price, bar_idx, role)]
    if current:
        clusters.append(current)

    out: list[dict[str, Any]] = []
    for cluster in clusters:
        prices = [x[0] for x in cluster]
        bars = [x[1] for x in cluster]
        roles = [x[2] for x in cluster]
        # Один кластер — одна роль (все support или все resistance)
        origin_role = roles[0] if roles else ORIGIN_SUPPORT
        median_price = sorted(prices)[len(prices) // 2]
        last_bar = max(bars)
        touches = len(cluster)
        out.append({
            "price": median_price,
            "bar_index": last_bar,
            "origin_role": origin_role,
            "touches": touches,
            "strength": min(1.0, 0.3 + 0.1 * touches),
        })
    return out


def _add_volume_at_level(
    levels: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    atr_period: int = 14,
    zone_atr_mult: float = 0.5,
    margin_pct_min: float = 0.001,
) -> list[dict[str, Any]]:
    """
    Суммарный объём в зоне уровня: свечи, чей [low, high] пересекает [price - margin, price + margin].
    margin = max(margin_pct_min * price, zone_atr_mult * ATR).
    Добавляет volume_at_level в каждый уровень.
    """
    if not candles or not levels:
        return levels
    atr_val = _atr(candles, atr_period)
    atr_val = atr_val if atr_val and atr_val > 0 else (candles[-1]["high"] - candles[-1]["low"]) if candles else 0.0
    for lev in levels:
        price = lev["price"]
        if price <= 0:
            lev["volume_at_level"] = 0.0
            continue
        margin = max(margin_pct_min * price, zone_atr_mult * atr_val)
        lo, hi = price - margin, price + margin
        vol = 0.0
        for c in candles:
            if c["low"] <= hi and c["high"] >= lo:
                vol += c.get("volume", 0.0)
        lev["volume_at_level"] = vol
    return levels


def _add_zone_width(
    levels: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    atr_period: int = 14,
    zone_atr_mult: float = 0.5,
) -> list[dict[str, Any]]:
    """
    Ширина зоны уровня: level_zone_low = price - 0.5*ATR, level_zone_high = price + 0.5*ATR.
    «Цена у уровня» = цена в [level_zone_low, level_zone_high].
    """
    if not candles or not levels:
        return levels
    atr_val = _atr(candles, atr_period)
    atr_val = atr_val if atr_val and atr_val > 0 else (candles[-1]["high"] - candles[-1]["low"]) if candles else 0.0
    half = zone_atr_mult * atr_val
    for lev in levels:
        p = lev["price"]
        lev["level_zone_low"] = p - half
        lev["level_zone_high"] = p + half
    return levels


def _add_round_bonus(
    levels: list[dict[str, Any]],
    round_step: float | None = None,
    near_pct: float = 0.001,
) -> list[dict[str, Any]]:
    """
    Бонус к силе для уровней рядом с круглыми числами (95k, 100k для BTC).
    round_step: шаг круглого уровня (None = авто по цене: 500 для 50k–100k, 1000 для 100k+).
    near_pct: в пределах этой доли от round — считаем «у круглого», бонус 0..1.
    """
    if not levels:
        return levels
    for lev in levels:
        price = lev["price"]
        if price <= 0:
            lev["near_round_number"] = False
            lev["round_bonus"] = 0.0
            continue
        step = round_step
        if step is None or step <= 0:
            if price >= 100_000:
                step = 1000.0
            elif price >= 10_000:
                step = 500.0
            else:
                step = max(50.0, price * 0.01)
        nearest = round(price / step) * step
        dist_pct = abs(price - nearest) / price if price > 0 else 1.0
        near = dist_pct <= near_pct
        bonus = max(0.0, 1.0 - dist_pct / near_pct) if near_pct > 0 else (1.0 if near else 0.0)
        lev["near_round_number"] = near
        lev["round_bonus"] = round(min(1.0, bonus), 3)
    return levels


def _add_recency(
    levels: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    decay_bars: float = 50.0,
) -> list[dict[str, Any]]:
    """
    Свежесть уровня: recency = 1 / (1 + age_bars / decay_bars). Старые уровни ослабляются.
    """
    if not candles or not levels:
        return levels
    n_bars = len(candles)
    for lev in levels:
        bar_idx = lev.get("bar_index", 0)
        age = max(0, n_bars - 1 - bar_idx)
        recency = 1.0 / (1.0 + age / decay_bars) if decay_bars > 0 else 1.0
        lev["recency"] = round(recency, 4)
    return levels


def _apply_composite_strength(
    levels: list[dict[str, Any]],
    weight_touches: float = 0.35,
    weight_volume: float = 0.25,
    weight_recency: float = 0.25,
    weight_round: float = 0.15,
) -> list[dict[str, Any]]:
    """
    Сводная сила уровня (0..1): взвешенная сумма от touches, volume_ratio, recency, round_bonus.
    """
    if not levels:
        return levels
    touches_max = max((l.get("touches", 0) for l in levels), default=1)
    vols = [l.get("volume_at_level", 0.0) for l in levels]
    median_vol = sorted(vols)[len(vols) // 2] if vols else 0.0
    for lev in levels:
        touches_norm = min(1.0, (lev.get("touches", 0) / touches_max) if touches_max > 0 else 0.0)
        vol = lev.get("volume_at_level", 0.0)
        volume_ratio = min(1.0, vol / median_vol) if median_vol > 0 else 0.0
        recency = lev.get("recency", 1.0)
        round_bonus = lev.get("round_bonus", 0.0)
        strength = (
            weight_touches * touches_norm
            + weight_volume * volume_ratio
            + weight_recency * recency
            + weight_round * round_bonus
        )
        lev["strength"] = round(min(1.0, max(0.0, strength)), 3)
    return levels


def _volume_ma(candles: list[dict[str, Any]], end_idx: int, period: int = 20) -> float:
    """Средний объём за period баров до end_idx (включительно)."""
    start = max(0, end_idx - period + 1)
    vol = [candles[i].get("volume", 0.0) for i in range(start, end_idx + 1)]
    return sum(vol) / len(vol) if vol else 0.0


def _assign_current_roles(
    levels: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    volume_confirm_ratio: float = 0.5,
    volume_ma_period: int = 20,
) -> list[dict[str, Any]]:
    """
    Для каждого уровня по истории свечей от бара образования до конца определяет:
    был ли пробой (close выше resistance / ниже support) и текущую роль (current_role, broken).
    Подтверждение пробоя: переключаем роль только если объём на баре пробоя >= volume_confirm_ratio * MA(volume, 20).
    """
    if not candles:
        return levels
    closes = [c["close"] for c in candles]
    for lev in levels:
        price = lev["price"]
        bar_start = lev["bar_index"]
        origin = lev["origin_role"]
        broken = False
        broken_at_bar: int | None = None
        if origin == ORIGIN_RESISTANCE:
            for j in range(bar_start + 1, len(closes)):
                if closes[j] > price:
                    vol_j = candles[j].get("volume", 0.0)
                    avg_vol = _volume_ma(candles, j, volume_ma_period)
                    if avg_vol <= 0 or vol_j >= volume_confirm_ratio * avg_vol:
                        broken = True
                        broken_at_bar = j
                    break
            current_role = CURRENT_SUPPORT if broken else CURRENT_RESISTANCE
        else:
            for j in range(bar_start + 1, len(closes)):
                if closes[j] < price:
                    vol_j = candles[j].get("volume", 0.0)
                    avg_vol = _volume_ma(candles, j, volume_ma_period)
                    if avg_vol <= 0 or vol_j >= volume_confirm_ratio * avg_vol:
                        broken = True
                        broken_at_bar = j
                    break
            current_role = CURRENT_RESISTANCE if broken else CURRENT_SUPPORT
        lev["current_role"] = current_role
        lev["broken"] = broken
        lev["broken_at_bar"] = broken_at_bar
    return levels


def _nearest_support_resistance(
    levels: list[dict[str, Any]], close: float
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ближайшая поддержка снизу (current_role=support, price < close) и сопротивление сверху (resistance, price > close)."""
    supports_below = [l for l in levels if l["current_role"] == CURRENT_SUPPORT and l["price"] < close]
    resistances_above = [l for l in levels if l["current_role"] == CURRENT_RESISTANCE and l["price"] > close]
    nearest_support = max(supports_below, key=lambda l: l["price"]) if supports_below else None
    nearest_resistance = min(resistances_above, key=lambda l: l["price"]) if resistances_above else None
    return nearest_support, nearest_resistance


def _recent_flips(
    levels: list[dict[str, Any]], candles: list[dict[str, Any]], lookback_bars: int = 20
) -> list[dict[str, Any]]:
    """Уровни, у которых роль сменилась (broken) и пробой произошёл в последних lookback_bars барах."""
    if not candles or lookback_bars <= 0:
        return []
    n = len(candles)
    from_bar = max(0, n - lookback_bars)
    return [
        l for l in levels
        if l.get("broken") and l.get("broken_at_bar") is not None and l["broken_at_bar"] >= from_bar
    ]


def detect_trading_zones(
    candles: list[dict[str, Any]],
    pivot_left: int = 3,
    pivot_right: int = 3,
    cluster_threshold_pct: float = 0.002,
    max_levels: int | None = 12,
    recent_flip_lookback_bars: int = 20,
    volume_confirm_ratio: float = 0.5,
    volume_ma_period: int = 20,
) -> dict[str, Any]:
    """
    Определяет торговые зоны: уровни с текущими ролями (support/resistance) и перевороты.

    Параметры:
      candles — OHLCV свечи (от старых к новым).
      pivot_left, pivot_right — окно для определения свинг-пивотов.
      cluster_threshold_pct — порог объединения близких уровней (0.002 = 0.2%).
      max_levels — максимум уровней в выдаче (по силе/свежести); None = все найденные уровни.
      recent_flip_lookback_bars — в каком окне считать «недавний» переворот роли.

    Возвращает:
      levels — список уровней (price, origin_role, current_role, broken, touches, strength, ...).
      nearest_support / nearest_resistance — ближайшие уровни снизу/сверху от текущей цены.
      zone_low / zone_high — границы текущей зоны (support price снизу, resistance сверху).
      in_zone — цена между zone_low и zone_high.
      recent_flips — уровни, недавно сменившие роль.
      distance_to_support_pct / distance_to_resistance_pct — расстояния до ближайших уровней.
    """
    if not candles or len(candles) < pivot_left + pivot_right + 1:
        return _empty_result(candles)

    pivot_lows = _find_pivot_lows(candles, left_bars=pivot_left, right_bars=pivot_right)
    pivot_highs = _find_pivot_highs(candles, left_bars=pivot_left, right_bars=pivot_right)
    levels_with_origin: list[tuple[float, int, str]] = [
        (p, i, ORIGIN_SUPPORT) for p, i in pivot_lows
    ] + [(p, i, ORIGIN_RESISTANCE) for p, i in pivot_highs]

    if not levels_with_origin:
        return _empty_result(candles)

    levels = _cluster_levels(levels_with_origin, threshold_pct=cluster_threshold_pct)
    levels = _add_volume_at_level(levels, candles)
    levels = _add_zone_width(levels, candles)
    levels = _add_round_bonus(levels)
    levels = _add_recency(levels, candles)
    levels = _apply_composite_strength(levels)
    # Сортируем по composite strength и свежести; при max_levels=None оставляем все уровни
    levels.sort(key=lambda l: (l["strength"], l["bar_index"]), reverse=True)
    if max_levels is not None:
        levels = levels[:max_levels]
    levels = _assign_current_roles(
        levels, candles,
        volume_confirm_ratio=volume_confirm_ratio,
        volume_ma_period=volume_ma_period,
    )

    close = candles[-1]["close"]
    if close <= 0:
        return _empty_result(candles)

    nearest_support, nearest_resistance = _nearest_support_resistance(levels, close)
    zone_low = nearest_support["price"] if nearest_support else None
    zone_high = nearest_resistance["price"] if nearest_resistance else None
    in_zone = (
        zone_low is not None and zone_high is not None and zone_low <= close <= zone_high
    )
    # «Цена у уровня» = в зоне ±ATR уровня
    at_support_zone = (
        nearest_support is not None
        and nearest_support.get("level_zone_low") is not None
        and nearest_support.get("level_zone_high") is not None
        and nearest_support["level_zone_low"] <= close <= nearest_support["level_zone_high"]
    )
    at_resistance_zone = (
        nearest_resistance is not None
        and nearest_resistance.get("level_zone_low") is not None
        and nearest_resistance.get("level_zone_high") is not None
        and nearest_resistance["level_zone_low"] <= close <= nearest_resistance["level_zone_high"]
    )

    distance_to_support_pct = None
    if nearest_support and nearest_support["price"] > 0:
        distance_to_support_pct = round((close - nearest_support["price"]) / close, 4)
    distance_to_resistance_pct = None
    if nearest_resistance and nearest_resistance["price"] > 0:
        distance_to_resistance_pct = round((nearest_resistance["price"] - close) / close, 4)

    recent_flips = _recent_flips(levels, candles, lookback_bars=recent_flip_lookback_bars)

    return {
        "levels": levels,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "in_zone": in_zone,
        "at_support_zone": at_support_zone,
        "at_resistance_zone": at_resistance_zone,
        "close": close,
        "recent_flips": recent_flips,
        "distance_to_support_pct": distance_to_support_pct,
        "distance_to_resistance_pct": distance_to_resistance_pct,
    }


def _empty_result(candles: list[dict[str, Any]]) -> dict[str, Any]:
    close = candles[-1]["close"] if candles else 0.0
    return {
        "levels": [],
        "nearest_support": None,
        "nearest_resistance": None,
        "zone_low": None,
        "zone_high": None,
        "in_zone": False,
        "at_support_zone": False,
        "at_resistance_zone": False,
        "close": close,
        "recent_flips": [],
        "distance_to_support_pct": None,
        "distance_to_resistance_pct": None,
    }
