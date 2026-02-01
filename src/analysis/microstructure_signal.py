"""
Сигнал по микроструктуре рынка (Order Flow): DOM, Volume Delta, Sweeps.

Принимает результат analyze_orderflow() и возвращает направление (long/short/none)
и уверенность на основе: дельты объёмов, imbalance стакана, недавних sweep'ов.
Используется как отдельный «голос» для комбинирования с мультиТФ-сигналом.
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
) -> dict[str, Any]:
    """
    Сигнал по микроструктуре: long / short / none и уверенность (0..1).

    of_result: результат analyze_orderflow() — dom, time_and_sales, volume_delta, sweeps.
    delta_ratio_min: порог delta_ratio для учёта дельты (например 0.15 = 15% перевес buy/sell).
    imbalance_eps: отклонение imbalance_ratio от 0.5 для учёта стакана (0.08 = 0.42..0.58 нейтрально).
    sweep_weight: вклад последнего sweep в итоговый score (0.3 = до ±0.3).
    min_score_for_direction: минимальный |score| для выдачи long/short (иначе none).

    Возвращает: direction (long|short|none), confidence (0..1), reason (строка), details (score, вклады).
    """
    dom = of_result.get("dom") or {}
    delta = of_result.get("volume_delta") or {}
    sweeps = of_result.get("sweeps") or {}

    delta_ratio = float(delta.get("delta_ratio") or 0.0)
    imbalance_ratio = float(dom.get("imbalance_ratio") or 0.5)
    last_sweep = (sweeps.get("last_sweep_side") or "").strip().lower()

    # Вклады в score от -1 до +1 (положительный = бычий)
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
        sweep_contrib = sweep_weight  # сметание низа → отскок вверх
    elif last_sweep == "ask":
        sweep_contrib = -sweep_weight  # сметание верха → отскок вниз

    score = max(-1.0, min(1.0, delta_contrib + imbalance_contrib + sweep_contrib))
    confidence = abs(score)

    if score >= min_score_for_direction:
        direction = "long"
        reason = _reason_parts(delta_contrib, imbalance_contrib, sweep_contrib, last_sweep, "long")
    elif score <= -min_score_for_direction:
        direction = "short"
        reason = _reason_parts(delta_contrib, imbalance_contrib, sweep_contrib, last_sweep, "short")
    else:
        direction = "none"
        reason = "микроструктура нейтральна (delta/imbalance/sweep не дают порога)"

    return {
        "direction": direction,
        "confidence": round(confidence, 3),
        "reason": reason,
        "details": {
            "score": round(score, 3),
            "delta_contribution": round(delta_contrib, 3),
            "imbalance_contribution": round(imbalance_contrib, 3),
            "sweep_contribution": round(sweep_contrib, 3),
            "delta_ratio": round(delta_ratio, 3),
            "imbalance_ratio": round(imbalance_ratio, 3),
            "last_sweep_side": sweeps.get("last_sweep_side"),
        },
    }


def _reason_parts(
    delta_contrib: float,
    imbalance_contrib: float,
    sweep_contrib: float,
    last_sweep: str,
    side: str,
) -> str:
    parts = []
    if abs(delta_contrib) >= 0.1:
        parts.append("delta " + ("в плюс" if delta_contrib > 0 else "в минус"))
    if abs(imbalance_contrib) >= 0.05:
        parts.append("imbalance " + ("bid" if imbalance_contrib > 0 else "ask"))
    if last_sweep and abs(sweep_contrib) >= 0.1:
        parts.append(f"sweep {last_sweep}")
    if not parts:
        return f"микроструктура с лёгким уклоном в {side}"
    return " | ".join(parts)
