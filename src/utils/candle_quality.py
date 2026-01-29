"""
Проверка качества данных свечей перед использованием в анализе.
Валидация структуры OHLCV, целостности и разумных границ.
"""
from __future__ import annotations

import math
from typing import Any


def validate_candles(
    candles: list[dict[str, Any]],
    timeframe: str | None = None,
    *,
    require_volume: bool = True,
    check_gaps: bool = False,
) -> dict[str, Any]:
    """
    Проверяет список свечей на корректность и возвращает результат с отфильтрованным списком и списком замечаний.

    Проверки:
    - наличие обязательных полей: start_time, open, high, low, close, volume
    - OHLC-логика: low <= open, close <= high; low <= high
    - числовые поля не NaN и не None
    - объём >= 0 (при require_volume=True можно требовать > 0 для последних баров)
    - опционально: пропуски по времени (check_gaps) для ожидаемого интервала ТФ

    Возвращает:
      valid: bool — прошли ли все критические проверки
      filtered: list — список свечей с исправленными/отброшенными некорректными
      issues: list[str] — список замечаний
      quality_score: float 0..1 — оценка качества (1 = идеально)
      invalid_count: int — сколько баров отброшено
    """
    issues: list[str] = []
    filtered: list[dict[str, Any]] = []
    invalid_count = 0
    required_keys = ("start_time", "open", "high", "low", "close", "volume")

    for i, c in enumerate(candles):
        if not isinstance(c, dict):
            invalid_count += 1
            issues.append(f"бар {i}: не словарь")
            continue

        missing = [k for k in required_keys if k not in c]
        if missing:
            invalid_count += 1
            issues.append(f"бар {i}: нет полей {missing}")
            continue

        try:
            start_time = c["start_time"]
            o = float(c["open"]) if c["open"] is not None else None
            h = float(c["high"]) if c["high"] is not None else None
            low = float(c["low"]) if c["low"] is not None else None
            cl = float(c["close"]) if c["close"] is not None else None
            vol = float(c["volume"]) if c["volume"] is not None else None
        except (TypeError, ValueError):
            invalid_count += 1
            issues.append(f"бар {i}: нечисловые OHLCV")
            continue

        if start_time is None:
            invalid_count += 1
            issues.append(f"бар {i}: start_time отсутствует")
            continue
        try:
            start_time = int(start_time)
        except (TypeError, ValueError):
            invalid_count += 1
            issues.append(f"бар {i}: start_time не int")
            continue

        if o is None or h is None or low is None or cl is None or vol is None:
            invalid_count += 1
            issues.append(f"бар {i}: None в OHLCV")
            continue

        if math.isnan(o) or math.isnan(h) or math.isnan(low) or math.isnan(cl) or math.isnan(vol):
            invalid_count += 1
            issues.append(f"бар {i}: NaN в OHLCV")
            continue

        if vol < 0:
            invalid_count += 1
            issues.append(f"бар {i}: объём < 0")
            continue

        if low > h:
            invalid_count += 1
            issues.append(f"бар {i}: low > high")
            continue

        if o < low or o > h or cl < low or cl > h:
            invalid_count += 1
            issues.append(f"бар {i}: open/close вне [low, high]")
            continue

        filtered.append({
            "start_time": start_time,
            "open": o,
            "high": h,
            "low": low,
            "close": cl,
            "volume": vol,
        })

    # Оценка качества 0..1: доля валидных баров, минус штраф за много замечаний
    n = len(candles)
    if n == 0:
        quality_score = 0.0
        valid = False
    else:
        ratio_ok = len(filtered) / n
        issue_penalty = min(0.3, len(issues) * 0.02)  # макс штраф 0.3
        quality_score = max(0.0, min(1.0, ratio_ok - issue_penalty))
        valid = len(filtered) >= 30 and ratio_ok >= 0.95  # критично: достаточно баров и почти все валидны

    # Опционально: проверка пропусков по времени (для минутных ТФ в мс)
    if check_gaps and timeframe and len(filtered) >= 2:
        interval_ms = _timeframe_to_ms(timeframe)
        if interval_ms and interval_ms > 0:
            for j in range(1, min(len(filtered), 50)):  # последние 50 баров
                prev_ts = filtered[len(filtered) - 1 - j]["start_time"]
                curr_ts = filtered[len(filtered) - j]["start_time"]
                if curr_ts - prev_ts > interval_ms * 1.5:  # пропуск больше 1.5 интервала
                    issues.append(f"пропуск времени между барами: {curr_ts - prev_ts} мс (ожидалось ~{interval_ms})")
                    break

    return {
        "valid": valid,
        "filtered": filtered,
        "issues": issues[:20],  # не более 20 замечаний в отчёте
        "quality_score": round(quality_score, 3),
        "invalid_count": invalid_count,
        "total_count": n,
    }


def _timeframe_to_ms(tf: str) -> int | None:
    """Приблизительный интервал таймфрейма в миллисекундах."""
    if tf == "D":
        return 24 * 60 * 60 * 1000
    if tf == "W":
        return 7 * 24 * 60 * 60 * 1000
    if tf == "M":
        return None  # переменный
    try:
        return int(tf) * 60 * 1000
    except ValueError:
        return None
