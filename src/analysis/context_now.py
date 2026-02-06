"""
Контекст «здесь и сейчас»: цена у уровня + flow за короткое окно + последний sweep.

Для режима «как проп-трейдеры» — решение от того, что происходит в текущую минуту:
уровень (поддержка/сопротивление), дельта за короткое окно, last_sweep.
Возвращает at_support, at_resistance, flow_bullish_now, flow_bearish_now, allowed_long, allowed_short.
"""
from __future__ import annotations

from typing import Any


def _at_level_from_dom(
    current_price: float,
    dom: dict[str, Any],
    level_distance_pct: float,
) -> tuple[bool, bool]:
    """at_support, at_resistance по значимым уровням стакана (bid ниже цены, ask выше)."""
    at_sup = False
    at_res = False
    levels = dom.get("significant_levels") or []
    if not levels or current_price <= 0:
        return at_sup, at_res
    for lev in levels:
        try:
            p = float(lev.get("price") or 0)
        except (TypeError, ValueError):
            continue
        side = str(lev.get("side") or "").strip().lower()
        if side == "bid" and p < current_price:
            dist_pct = (current_price - p) / current_price
            if dist_pct <= level_distance_pct:
                at_sup = True
        elif side == "ask" and p > current_price:
            dist_pct = (p - current_price) / current_price
            if dist_pct <= level_distance_pct:
                at_res = True
    return at_sup, at_res


def compute_context_now(
    current_price: float,
    of_result: dict[str, Any],
    trading_zones: dict[str, Any] | None,
    *,
    level_distance_pct: float = 0.0015,
    delta_ratio_min: float = 0.12,
    use_dom_levels: bool = False,
) -> dict[str, Any]:
    """
    Контекст «здесь и сейчас»: у уровня ли цена, куда flow в коротком окне, последний sweep.

    current_price: текущая цена (mid из стакана).
    of_result: результат analyze_orderflow() — dom, volume_delta, short_window_delta, sweeps, last_trades.
    trading_zones: report["trading_zones"] — nearest_support, nearest_resistance (игнорируются при use_dom_levels=True).
    level_distance_pct: цена в пределах этой доли от уровня = «у уровня» (0.0015 = 0.15%).
    delta_ratio_min: порог delta_ratio в коротком окне для flow_bullish_now / flow_bearish_now.
    use_dom_levels: True = at_support/at_resistance по значимым уровням стакана (DOM), иначе по trading_zones.

    Возвращает: at_support, at_resistance, flow_bullish_now, flow_bearish_now, allowed_long, allowed_short,
    last_trades_bias, last_block_side, last_sweep_side, short_window_delta_ratio, ...
    """
    at_support = False
    at_resistance = False
    in_zone = False
    distance_to_support_pct = None
    distance_to_resistance_pct = None

    if use_dom_levels and of_result.get("dom"):
        at_support, at_resistance = _at_level_from_dom(
            current_price, of_result["dom"], level_distance_pct
        )
    else:
        zones = trading_zones or {}
        ns = zones.get("nearest_support")
        nr = zones.get("nearest_resistance")
        zone_low = zones.get("zone_low")
        zone_high = zones.get("zone_high")

        if current_price > 0:
            if ns is not None and ns.get("price") is not None:
                sup_price = float(ns["price"])
                dist_pct = (current_price - sup_price) / current_price
                distance_to_support_pct = round(dist_pct, 4)
                if sup_price > 0 and dist_pct >= 0 and dist_pct <= level_distance_pct:
                    at_support = True
                elif ns.get("level_zone_low") is not None and ns.get("level_zone_high") is not None:
                    low_z = float(ns["level_zone_low"])
                    high_z = float(ns["level_zone_high"])
                    if low_z <= current_price <= high_z:
                        at_support = True
            if nr is not None and nr.get("price") is not None:
                res_price = float(nr["price"])
                dist_pct = (res_price - current_price) / current_price
                distance_to_resistance_pct = round(dist_pct, 4)
                if res_price > 0 and dist_pct >= 0 and dist_pct <= level_distance_pct:
                    at_resistance = True
                elif nr.get("level_zone_low") is not None and nr.get("level_zone_high") is not None:
                    low_z = float(nr["level_zone_low"])
                    high_z = float(nr["level_zone_high"])
                    if low_z <= current_price <= high_z:
                        at_resistance = True
            if zone_low is not None and zone_high is not None:
                try:
                    in_zone = float(zone_low) <= current_price <= float(zone_high)
                except (TypeError, ValueError):
                    in_zone = False

    short_delta = of_result.get("short_window_delta") or {}
    delta_ratio_short = float(short_delta.get("delta_ratio") or 0.0)
    flow_bullish_now = delta_ratio_short >= delta_ratio_min
    flow_bearish_now = delta_ratio_short <= -delta_ratio_min

    sweeps = of_result.get("sweeps") or {}
    last_sweep_side = (sweeps.get("last_sweep_side") or "").strip().lower() or None
    lt = of_result.get("last_trades") or {}
    last_trades_bias = (lt.get("last_trades_bias") or "neutral").strip().lower()
    last_block_side = (lt.get("last_block_side") or "").strip().lower() or None

    absorption = of_result.get("absorption") or {}
    absorption_bullish = bool(absorption.get("absorption_bullish"))
    absorption_bearish = bool(absorption.get("absorption_bearish"))
    allowed_long = (at_support and (flow_bullish_now or absorption_bullish))
    allowed_short = (at_resistance and (flow_bearish_now or absorption_bearish))

    return {
        "at_support": at_support,
        "at_resistance": at_resistance,
        "in_zone": in_zone,
        "flow_bullish_now": flow_bullish_now,
        "flow_bearish_now": flow_bearish_now,
        "absorption_bullish": absorption_bullish,
        "absorption_bearish": absorption_bearish,
        "last_sweep_side": last_sweep_side,
        "last_trades_bias": last_trades_bias,
        "last_block_side": last_block_side,
        "short_window_delta_ratio": round(delta_ratio_short, 4),
        "distance_to_support_pct": distance_to_support_pct,
        "distance_to_resistance_pct": distance_to_resistance_pct,
        "allowed_long": allowed_long,
        "allowed_short": allowed_short,
    }
