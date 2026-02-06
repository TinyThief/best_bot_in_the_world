"""
Сигнал по микроструктуре рынка (Order Flow): DOM, Time & Sales, Volume Delta, Sweeps.

Принимает результат analyze_orderflow() и возвращает направление (long/short/none),
уверенность, reason и exit_hints на основе: дельты объёмов, imbalance стакана, T&S,
недавних sweep'ов (с реценцией и количеством), стен стакана, динамики дельты,
конфликта компонентов и обработки пустых данных.
"""
from __future__ import annotations

from typing import Any


def compute_microstructure_signal(
    of_result: dict[str, Any],
    *,
    delta_ratio_min: float = 0.15,
    imbalance_eps: float = 0.08,
    sweep_weight: float = 0.3,
    min_score_for_direction: float = 0.25,
    min_score_long: float | None = None,
    min_score_short: float | None = None,
    current_price: float | None = None,
    now_ts_sec: int | None = None,
    volume_spike_penalty: float = 0.15,
    low_volume_ratio_min: float = 0.0,
    sweep_decay_sec: float = 120.0,
    conflict_penalty: float = 0.25,
    wall_weight: float = 0.1,
    delta_trend_weight: float = 0.2,
    use_time_and_sales: bool = True,
    use_sweep_decay: bool = True,
    use_conflict_penalty: bool = True,
    use_dom_walls: bool = True,
    use_delta_trend: bool = True,
    handle_empty_data: bool = True,
    min_delta_imbalance_contrib_for_confirm: float = 0.05,
) -> dict[str, Any]:
    """
    Сигнал по микроструктуре: long / short / none, уверенность (0..1), reason, exit_hints.

    of_result: результат analyze_orderflow() — dom, time_and_sales, volume_delta, sweeps.
    current_price: текущая цена (mid) для учёта стен стакана относительно цены; опционально.
    now_ts_sec: текущее время в секундах для затухания sweep по возрасту; опционально.
    min_score_long / min_score_short: пороги для long/short по отдельности; если None — min_score_for_direction.
    volume_spike_penalty: снижение confidence при всплеске объёма (T&S).
    low_volume_ratio_min: порог «низкий объём» (доля от типичного); 0 = не штрафовать.
    sweep_decay_sec: за сколько секунд вклад последнего sweep затухает до нуля.
    conflict_penalty: снижение confidence при противоречии компонентов (delta/imbalance/sweep).
    wall_weight: макс. вклад стен стакана в score (±wall_weight).
    delta_trend_weight: макс. вклад динамики дельты (вторая половина окна − первая).
    use_*: включение T&S, затухания sweep, штрафа за конфликт, стен, тренда дельты, обработки пустых данных.
    min_delta_imbalance_contrib_for_confirm: порог вклада delta/imbalance; если оба ниже — sweep_only=True (защита от ловушек).

    Возвращает: direction, confidence, reason, sweep_only, details, exit_hints (список подсказок для выхода).
    """
    dom = of_result.get("dom") or {}
    tns = of_result.get("time_and_sales") or {}
    delta = of_result.get("volume_delta") or {}
    sweeps = of_result.get("sweeps") or {}

    # --- 6. Пустые/частичные данные ---
    no_trades = False
    if handle_empty_data:
        if not dom or not isinstance(dom, dict) or len(dom) == 0:
            return {
                "direction": "none",
                "confidence": 0.0,
                "reason": "нет данных стакана",
                "sweep_only": False,
                "details": {"score": 0.0, "empty": "dom", "delta_ratio": 0.0, "imbalance_ratio": 0.5},
                "exit_hints": [],
            }
        trades_count = int(delta.get("trades_count") or 0)
        if trades_count == 0 and use_time_and_sales:
            no_trades = True

    delta_ratio = float(delta.get("delta_ratio") or 0.0)
    first_half_ratio = float(delta.get("first_half_delta_ratio") or 0.0)
    second_half_ratio = float(delta.get("second_half_delta_ratio") or 0.0)
    imbalance_ratio = float(dom.get("imbalance_ratio") or 0.5)
    last_sweep = (sweeps.get("last_sweep_side") or "").strip().lower()
    last_sweep_time = sweeps.get("last_sweep_time")
    recent_sweeps_bid = sweeps.get("recent_sweeps_bid") or []
    recent_sweeps_ask = sweeps.get("recent_sweeps_ask") or []

    # Базовые вклады в score (положительный = бычий). delta_ratio используем, если есть (при no_trades тренд дельты не считаем)
    delta_contrib = 0.0
    if delta_ratio >= delta_ratio_min:
        delta_contrib = min(0.4, 0.2 + (delta_ratio - delta_ratio_min) * 0.5)
    elif delta_ratio <= -delta_ratio_min:
        delta_contrib = max(-0.4, -0.2 + (delta_ratio + delta_ratio_min) * 0.5)

    imbalance_contrib = 0.0
    if imbalance_ratio >= 0.5 + imbalance_eps:
        imbalance_contrib = min(0.3, (imbalance_ratio - 0.5) * 2.0)
    elif imbalance_ratio <= 0.5 - imbalance_eps:
        imbalance_contrib = max(-0.3, (imbalance_ratio - 0.5) * 2.0)

    sweep_contrib = 0.0
    if last_sweep == "bid":
        sweep_contrib = sweep_weight
    elif last_sweep == "ask":
        sweep_contrib = -sweep_weight

    # --- 2. Реценция и количество sweep'ов ---
    if use_sweep_decay and now_ts_sec is not None and last_sweep_time is not None and last_sweep:
        # last_sweep_time может быть в мс (Bybit) или сек
        sweep_ts_sec = float(last_sweep_time) / 1000.0 if last_sweep_time > 1e12 else float(last_sweep_time)
        age_sec = max(0, now_ts_sec - sweep_ts_sec)
        if sweep_decay_sec > 0:
            decay = max(0.0, 1.0 - age_sec / sweep_decay_sec)
            sweep_contrib *= decay
        # Усиление при нескольких sweep'ах в одну сторону
        n_bid = len(recent_sweeps_bid)
        n_ask = len(recent_sweeps_ask)
        if n_bid > n_ask and last_sweep == "bid":
            sweep_contrib = min(sweep_weight, sweep_contrib + 0.05 * (n_bid - n_ask))
        elif n_ask > n_bid and last_sweep == "ask":
            sweep_contrib = max(-sweep_weight, sweep_contrib - 0.05 * (n_ask - n_bid))

    # --- 5. Динамика дельты ---
    trend_contrib = 0.0
    if use_delta_trend and not no_trades:
        delta_trend = second_half_ratio - first_half_ratio
        trend_contrib = max(-delta_trend_weight, min(delta_trend_weight, delta_trend * 0.5))

    # --- 4. Стены стакана относительно цены ---
    wall_contrib = 0.0
    if use_dom_walls and current_price is not None and current_price > 0:
        levels = dom.get("significant_levels") or []
        contrib_per_wall = (wall_weight / 5.0) if len(levels) > 0 else 0
        for lev in levels:
            p = lev.get("price")
            if p is None:
                continue
            try:
                price = float(p)
            except (TypeError, ValueError):
                continue
            side = str(lev.get("side") or "").strip().lower()
            # Стена на bid ниже цены — поддержка (бычий); стена на ask выше цены — сопротивление (медвежий)
            if side == "bid" and price < current_price:
                wall_contrib += contrib_per_wall
            elif side == "ask" and price > current_price:
                wall_contrib -= contrib_per_wall
        wall_contrib = max(-wall_weight, min(wall_weight, wall_contrib))

    score = max(
        -1.0,
        min(1.0, delta_contrib + imbalance_contrib + sweep_contrib + trend_contrib + wall_contrib),
    )
    confidence = abs(score)

    # --- 3. Конфликт компонентов ---
    if use_conflict_penalty and conflict_penalty > 0:
        signs = []
        if abs(delta_contrib) >= 0.05:
            signs.append(1 if delta_contrib > 0 else -1)
        if abs(imbalance_contrib) >= 0.05:
            signs.append(1 if imbalance_contrib > 0 else -1)
        if abs(sweep_contrib) >= 0.05:
            signs.append(1 if sweep_contrib > 0 else -1)
        if abs(trend_contrib) >= 0.05:
            signs.append(1 if trend_contrib > 0 else -1)
        if len(signs) >= 2 and not all(s == signs[0] for s in signs):
            confidence = max(0.0, confidence * (1.0 - conflict_penalty))

    # --- 1. Time & Sales: всплеск объёма и низкий объём ---
    if use_time_and_sales:
        is_spike = bool(tns.get("is_volume_spike"))
        total_vol = float(tns.get("total_volume") or 0)
        if is_spike and volume_spike_penalty > 0:
            confidence = max(0.0, confidence * (1.0 - volume_spike_penalty))
        if low_volume_ratio_min > 0 and total_vol >= 0:
            # Низкий объём относительно порога (порог задаётся снаружи или по умолчанию не применяем)
            pass

    # --- 7. Пороги для long/short (симметричные или раздельные) ---
    min_long = min_score_long if min_score_long is not None else min_score_for_direction
    min_short = min_score_short if min_score_short is not None else min_score_for_direction

    if score >= min_long:
        direction = "long"
        reason = _reason_parts(
            delta_contrib, imbalance_contrib, sweep_contrib, last_sweep, "long",
            trend_contrib, wall_contrib,
        )
    elif score <= -min_short:
        direction = "short"
        reason = _reason_parts(
            delta_contrib, imbalance_contrib, sweep_contrib, last_sweep, "short",
            trend_contrib, wall_contrib,
        )
    else:
        direction = "none"
        reason = "микроструктура нейтральна (delta/imbalance/sweep/тренд не дают порога)"

    # --- 8a. Флаг «только sweep» (защита от ловушек: не входить по одному sweep без delta/imbalance) ---
    sweep_only = (
        direction != "none"
        and abs(delta_contrib) < min_delta_imbalance_contrib_for_confirm
        and abs(imbalance_contrib) < min_delta_imbalance_contrib_for_confirm
    )

    # --- 8. Подсказки для выхода (exit_hints) ---
    exit_hints: list[str] = []
    if direction == "long":
        if last_sweep == "ask":
            exit_hints.append("sweep_against_long")
        if use_delta_trend and not no_trades:
            if second_half_ratio - first_half_ratio < -0.1:
                exit_hints.append("delta_weakening")
    elif direction == "short":
        if last_sweep == "bid":
            exit_hints.append("sweep_against_short")
        if use_delta_trend and not no_trades:
            if second_half_ratio - first_half_ratio > 0.1:
                exit_hints.append("delta_weakening")

    return {
        "direction": direction,
        "confidence": round(confidence, 3),
        "reason": reason,
        "sweep_only": sweep_only,
        "details": {
            "score": round(score, 3),
            "delta_contribution": round(delta_contrib, 3),
            "imbalance_contribution": round(imbalance_contrib, 3),
            "sweep_contribution": round(sweep_contrib, 3),
            "trend_contribution": round(trend_contrib, 3),
            "wall_contribution": round(wall_contrib, 3),
            "delta_ratio": round(delta_ratio, 3),
            "first_half_delta_ratio": round(first_half_ratio, 3),
            "second_half_delta_ratio": round(second_half_ratio, 3),
            "imbalance_ratio": round(imbalance_ratio, 3),
            "last_sweep_side": sweeps.get("last_sweep_side"),
            "recent_sweeps_bid": len(recent_sweeps_bid),
            "recent_sweeps_ask": len(recent_sweeps_ask),
        },
        "exit_hints": exit_hints,
    }


def _reason_parts(
    delta_contrib: float,
    imbalance_contrib: float,
    sweep_contrib: float,
    last_sweep: str,
    side: str,
    trend_contrib: float = 0.0,
    wall_contrib: float = 0.0,
) -> str:
    parts = []
    if abs(delta_contrib) >= 0.1:
        parts.append("delta " + ("в плюс" if delta_contrib > 0 else "в минус"))
    if abs(imbalance_contrib) >= 0.05:
        parts.append("imbalance " + ("bid" if imbalance_contrib > 0 else "ask"))
    if last_sweep and abs(sweep_contrib) >= 0.1:
        parts.append(f"sweep {last_sweep}")
    if abs(trend_contrib) >= 0.05:
        parts.append("тренд дельты " + ("в плюс" if trend_contrib > 0 else "в минус"))
    if abs(wall_contrib) >= 0.03:
        parts.append("стены " + ("поддержка" if wall_contrib > 0 else "сопротивление"))
    if not parts:
        return f"микроструктура с лёгким уклоном в {side}"
    return " | ".join(parts)
