"""
Мультитаймфреймовый анализ: агрегация сигналов с нескольких таймфреймов.
Тренд на старшем ТФ + 6 фаз рынка (накопление, рост, распределение, падение, капитуляция, восстановление).
Источник свечей: DATA_SOURCE=db — из БД (по умолчанию), =exchange — запрос к Bybit на каждый тик.
Расчёт по каждому ТФ (quality, trend, phase, regime, momentum) выполняется параллельно.
"""
from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..core import config
from ..core.exchange import get_klines_multi_timeframe
from ..utils.candle_quality import validate_candles as validate_candles_quality
from .market_phases import BEARISH_PHASES, BULLISH_PHASES, _atr, _volume_ratio, detect_phase, swing_levels
from .market_trend import detect_momentum, detect_regime, detect_trend
from .trading_zones import detect_trading_zones

logger = logging.getLogger(__name__)

# История фаз по ТФ для расчёта устойчивости (последние N тиков).
_phase_history: dict[str, list[str]] = {}
# История трендов по ТФ для устойчивости тренда (последние N тиков).
_trend_history: dict[str, list[str]] = {}


def reset_multi_tf_history() -> None:
    """Сбрасывает историю фаз и трендов по ТФ (для бэктеста — чистое состояние на каждый прогон)."""
    global _phase_history, _trend_history
    _phase_history = {}
    _trend_history = {}


def _update_phase_stability(tf: str, phase: str) -> tuple[float, bool]:
    """
    Добавляет фазу в историю по ТФ, возвращает (phase_stability, phase_stable).
    stability — доля последних тиков с той же фазой; stable — stability >= PHASE_STABILITY_MIN.
    """
    history_size = getattr(config, "PHASE_HISTORY_SIZE", 5)
    stability_min = getattr(config, "PHASE_STABILITY_MIN", 0.6)
    hist = _phase_history.setdefault(tf, [])
    hist.append(phase)
    if len(hist) > history_size:
        hist.pop(0)
    if not hist:
        return 0.0, False
    same = sum(1 for p in hist if p == phase)
    stability = same / len(hist)
    return round(stability, 3), stability >= stability_min


def _update_trend_stability(tf: str, trend: str) -> tuple[float, bool]:
    """
    Добавляет тренд в историю по ТФ, возвращает (trend_stability, trend_stable).
    trend_stable = True если TREND_STABILITY_MIN == 0 или stability >= TREND_STABILITY_MIN.
    """
    history_size = getattr(config, "PHASE_HISTORY_SIZE", 5)
    stability_min = getattr(config, "TREND_STABILITY_MIN", 0.0)
    if stability_min <= 0:
        return 0.0, True
    hist = _trend_history.setdefault(tf, [])
    hist.append(trend)
    if len(hist) > history_size:
        hist.pop(0)
    if not hist:
        return 0.0, False
    same = sum(1 for t in hist if t == trend)
    stability = same / len(hist)
    return round(stability, 3), stability >= stability_min


def _analyze_single_timeframe(tf: str, candles_raw: list[dict[str, Any]]) -> tuple[str, list, dict, dict, dict, dict, dict]:
    """
    Независимый расчёт по одному ТФ: quality, trend, phase (без контекста старшего), regime, momentum.
    Возвращает (tf, candles, quality_result, trend_info, phase_info, regime_info, momentum_info).
    Не обновляет _phase_history / _trend_history — это делается последовательно после сбора.
    """
    default_quality = {
        "valid": False,
        "filtered": [],
        "issues": [],
        "quality_score": 0.0,
        "invalid_count": 0,
        "total_count": 0,
    }
    default_phase = {
        "phase": "accumulation",
        "phase_ru": "—",
        "score": 0.0,
        "details": {},
        "secondary_phase": None,
        "secondary_phase_ru": None,
        "secondary_score": 0.0,
        "score_gap": 0.0,
        "phase_unclear": True,
    }
    default_regime = {
        "regime": "range",
        "regime_ru": "Диапазон",
        "adx": None,
        "atr_ratio": None,
        "bb_width": None,
    }
    default_momentum = {
        "momentum_state": "neutral",
        "momentum_state_ru": "Нейтральный",
        "momentum_direction": "neutral",
        "momentum_direction_ru": "Нейтральный",
        "rsi": None,
        "return_5": None,
        "details": {},
    }
    quality_result = (
        validate_candles_quality(candles_raw, timeframe=tf)
        if candles_raw
        else default_quality
    )
    candles = quality_result.get("filtered") or candles_raw or []
    trend_info = (
        detect_trend(candles, timeframe=tf)
        if candles and len(candles) >= 30
        else _default_trend_info.copy()
    )
    phase_info = (
        detect_phase(candles, timeframe=tf)
        if candles and len(candles) >= 30
        else default_phase.copy()
    )
    regime_info = (
        detect_regime(candles, lookback=50)
        if candles and len(candles) >= 30
        else default_regime.copy()
    )
    momentum_info = (
        detect_momentum(candles)
        if candles and len(candles) >= 20
        else default_momentum.copy()
    )
    return (tf, candles, quality_result, trend_info, phase_info, regime_info, momentum_info)


def _load_candles_from_db(
    db_conn: sqlite3.Connection,
    symbol: str,
    intervals: list[str],
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    """Загружает последние limit свечей по каждому ТФ из БД. Формат как у get_klines_multi_timeframe."""
    from ..core.database import get_candles

    cursor = db_conn.cursor()
    out: dict[str, list[dict[str, Any]]] = {}
    for tf in intervals:
        try:
            rows = get_candles(cursor, symbol, tf, limit=limit, order_asc=False)
            out[tf] = rows  # уже от старых к новым
        except Exception as e:
            logger.warning("БД ТФ %s: %s", tf, e)
            out[tf] = []
    return out


# Дефолт тренда при недостатке данных (для совместимости с detect_trend).
_default_trend_info = {
    "direction": "flat",
    "direction_ru": "Флэт",
    "strength": 0.0,
    "trend_confidence": 0.0,
    "details": {},
    "trend_unclear": True,
    "secondary_direction": None,
    "secondary_direction_ru": None,
    "secondary_strength": 0.0,
    "strength_gap": 0.0,
    "bullish_score": 0.0,
    "bearish_score": 0.0,
}


def _tf_sort_key(tf: str) -> tuple[int, str]:
    """Порядок таймфреймов: младшие числа — раньше (15 < 60 < D)."""
    if tf == "D":
        return (1_000_000, "D")
    if tf == "W":
        return (2_000_000, "W")
    if tf == "M":
        return (3_000_000, "M")
    try:
        return (int(tf), tf)
    except ValueError:
        return (0, tf)


def _compute_multi_tf_result(
    data: dict[str, list[dict[str, Any]]],
    intervals: list[str],
    symbol: str,
) -> dict[str, Any]:
    """
    Внутренняя логика мультитаймфреймового анализа по готовым данным.
    data[tf] = список свечей (от старых к новым). Используется из analyze_multi_timeframe и analyze_multi_timeframe_from_data.
    """
    sorted_tfs = sorted(intervals, key=_tf_sort_key)
    higher_tf = sorted_tfs[-1] if sorted_tfs else None

    # Параллельный расчёт по каждому ТФ (quality, trend, phase без контекста, regime, momentum)
    results_by_tf: dict[str, tuple] = {}
    max_workers = min(len(sorted_tfs), 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_tf = {
            executor.submit(_analyze_single_timeframe, tf, data.get(tf) or []): tf
            for tf in sorted_tfs
        }
        for future in as_completed(future_to_tf):
            tf = future_to_tf[future]
            try:
                result = future.result()
                results_by_tf[tf] = result
            except Exception as e:
                logger.warning("Параллельный расчёт ТФ %s: %s", tf, e)
                results_by_tf[tf] = _analyze_single_timeframe(tf, data.get(tf) or [])

    # Последовательно: обновление истории устойчивости и сборка timeframes_report (порядок по sorted_tfs)
    timeframes_report: dict[str, dict[str, Any]] = {}
    candle_quality_min = getattr(config, "CANDLE_QUALITY_MIN_SCORE", 0.0)
    for tf in sorted_tfs:
        r = results_by_tf.get(tf)
        if r is None:
            continue
        _t, candles, quality_result, trend_info, phase_info, regime_info, momentum_info = r
        phase_stability, phase_stable = _update_phase_stability(tf, phase_info["phase"])
        trend_stability, trend_stable = _update_trend_stability(tf, trend_info["direction"])
        candle_quality_ok = (
            candle_quality_min <= 0
            or (quality_result.get("quality_score", 0) >= candle_quality_min and quality_result.get("valid", False))
        )
        timeframes_report[tf] = {
            "candles": candles,
            "candle_quality_ok": candle_quality_ok,
            "candle_quality_score": quality_result.get("quality_score"),
            "candle_quality_issues": quality_result.get("issues", [])[:5],
            "candle_invalid_count": quality_result.get("invalid_count", 0),
            "regime": regime_info["regime"],
            "regime_ru": regime_info.get("regime_ru", "—"),
            "regime_adx": regime_info.get("adx"),
            "regime_atr_ratio": regime_info.get("atr_ratio"),
            "regime_bb_width": regime_info.get("bb_width"),
            "trend": trend_info["direction"],
            "trend_ru": trend_info.get("direction_ru", "—"),
            "trend_strength": trend_info.get("strength", 0.0),
            "trend_confidence": trend_info.get("trend_confidence", 0.0),
            "trend_details": trend_info.get("details", {}),
            "trend_unclear": trend_info.get("trend_unclear", True),
            "secondary_trend": trend_info.get("secondary_direction"),
            "secondary_trend_ru": trend_info.get("secondary_direction_ru"),
            "secondary_trend_strength": trend_info.get("secondary_strength", 0.0),
            "trend_strength_gap": trend_info.get("strength_gap", 0.0),
            "bullish_score": trend_info.get("bullish_score", 0.0),
            "bearish_score": trend_info.get("bearish_score", 0.0),
            "trend_stability": trend_stability,
            "trend_stable": trend_stable,
            "phase": phase_info["phase"],
            "phase_ru": phase_info["phase_ru"],
            "phase_score": phase_info.get("score", 0),
            "phase_details": phase_info.get("details", {}),
            "secondary_phase": phase_info.get("secondary_phase"),
            "secondary_phase_ru": phase_info.get("secondary_phase_ru"),
            "secondary_score": phase_info.get("secondary_score", 0.0),
            "score_gap": phase_info.get("score_gap", 0.0),
            "phase_unclear": phase_info.get("phase_unclear", True),
            "phase_stability": phase_stability,
            "phase_stable": phase_stable,
            "momentum_state": momentum_info.get("momentum_state", "neutral"),
            "momentum_state_ru": momentum_info.get("momentum_state_ru", "Нейтральный"),
            "momentum_direction": momentum_info.get("momentum_direction", "neutral"),
            "momentum_direction_ru": momentum_info.get("momentum_direction_ru", "Нейтральный"),
            "momentum_rsi": momentum_info.get("rsi"),
            "momentum_return_5": momentum_info.get("return_5"),
        }

    # Контекст старшего ТФ для младших: пересчёт фаз с higher_tf_phase / higher_tf_trend
    if higher_tf:
        higher_tf_data = timeframes_report.get(higher_tf) or {}
        h_phase = higher_tf_data.get("phase")
        h_trend = higher_tf_data.get("trend", "flat")
        for tf in sorted_tfs:
            if tf == higher_tf:
                continue
            candles = (timeframes_report.get(tf) or {}).get("candles") or []
            if candles and len(candles) >= 30:
                phase_info = detect_phase(
                    candles, timeframe=tf, higher_tf_phase=h_phase, higher_tf_trend=h_trend
                )
                phase_stability, phase_stable = _update_phase_stability(tf, phase_info["phase"])
                timeframes_report[tf]["phase"] = phase_info["phase"]
                timeframes_report[tf]["phase_ru"] = phase_info["phase_ru"]
                timeframes_report[tf]["phase_score"] = phase_info.get("score", 0)
                timeframes_report[tf]["phase_details"] = phase_info.get("details", {})
                timeframes_report[tf]["secondary_phase"] = phase_info.get("secondary_phase")
                timeframes_report[tf]["secondary_phase_ru"] = phase_info.get("secondary_phase_ru")
                timeframes_report[tf]["secondary_score"] = phase_info.get("secondary_score", 0.0)
                timeframes_report[tf]["score_gap"] = phase_info.get("score_gap", 0.0)
                timeframes_report[tf]["phase_unclear"] = phase_info.get("phase_unclear", True)
                timeframes_report[tf]["phase_stability"] = phase_stability
                timeframes_report[tf]["phase_stable"] = phase_stable
    higher_tf_trend = (timeframes_report.get(higher_tf) or {}).get("trend", "flat")
    higher_tf_data = timeframes_report.get(higher_tf) or {}
    higher_tf_candles = higher_tf_data.get("candles") or []
    # Фильтры объёма и ATR по старшему ТФ
    volume_min_ratio = getattr(config, "VOLUME_MIN_RATIO", 0.0)
    atr_max_ratio = getattr(config, "ATR_MAX_RATIO", 0.0)
    vol_ratio = _volume_ratio(higher_tf_candles, short=5, long=20) if len(higher_tf_candles) >= 20 else None
    atr_now = _atr(higher_tf_candles, 14) if len(higher_tf_candles) >= 14 else None
    atr_prev = _atr(higher_tf_candles[:-5], 14) if len(higher_tf_candles) >= 19 else atr_now
    atr_ratio = (atr_now / atr_prev) if (atr_prev and atr_prev > 0 and atr_now is not None) else None
    volume_ok = volume_min_ratio <= 0 or (vol_ratio is not None and vol_ratio >= volume_min_ratio)
    atr_ok = atr_max_ratio <= 0 or (atr_ratio is not None and atr_ratio <= atr_max_ratio)
    # Уровни по свинг-точкам (HH/HL): поддержка и сопротивление, расстояние цены до них
    levels = swing_levels(higher_tf_candles, pivots=5) if len(higher_tf_candles) >= 10 else {}
    # Торговые зоны (динамические уровни с переключением ролей: сопротивление → поддержка и наоборот)
    _zones_max = getattr(config, "TRADING_ZONES_MAX_LEVELS", 0)
    _zones_max_levels_arg = None if _zones_max <= 0 else _zones_max
    trading_zones = (
        detect_trading_zones(higher_tf_candles, max_levels=_zones_max_levels_arg)
        if len(higher_tf_candles) >= 15
        else {"levels": [], "nearest_support": None, "nearest_resistance": None, "zone_low": None, "zone_high": None, "in_zone": False, "at_support_zone": False, "at_resistance_zone": False, "recent_flips": [], "distance_to_support_pct": None, "distance_to_resistance_pct": None}
    )
    # Конfluence зон по ТФ: один уровень на нескольких ТФ — сильнее
    _confluence_threshold_pct = 0.002
    if trading_zones.get("levels") and len(sorted_tfs) > 1:
        for lev in trading_zones["levels"]:
            lev["confluence_tfs"] = [higher_tf]
        for _tf in sorted_tfs:
            if _tf == higher_tf:
                continue
            _candles = (timeframes_report.get(_tf) or {}).get("candles") or []
            if len(_candles) < 15:
                continue
            _z = detect_trading_zones(_candles, max_levels=_zones_max_levels_arg)
            _other_prices = [lev["price"] for lev in (_z.get("levels") or [])]
            for lev in trading_zones["levels"]:
                p = lev.get("price")
                if p is None or p <= 0:
                    continue
                for _op in _other_prices:
                    if abs(_op - p) / p <= _confluence_threshold_pct:
                        if _tf not in lev["confluence_tfs"]:
                            lev["confluence_tfs"].append(_tf)
                        break
        levels_with_confluence = sum(1 for lev in trading_zones.get("levels") or [] if len(lev.get("confluence_tfs") or []) >= 2)
    else:
        levels_with_confluence = 0
        for lev in trading_zones.get("levels") or []:
            lev["confluence_tfs"] = [higher_tf] if higher_tf else []
    trading_zones["levels_with_confluence"] = levels_with_confluence
    # Расстояния до уровней: приоритет у зон (если есть), иначе свинг-уровни
    dist_support = trading_zones.get("distance_to_support_pct") if trading_zones.get("levels") else levels.get("distance_to_support_pct")
    dist_resistance = trading_zones.get("distance_to_resistance_pct") if trading_zones.get("levels") else levels.get("distance_to_resistance_pct")
    level_max = getattr(config, "LEVEL_MAX_DISTANCE_PCT", 0.0)
    level_ok = (
        level_max <= 0
        or (dist_support is not None and 0 <= dist_support <= level_max)
        or (dist_resistance is not None and 0 <= dist_resistance <= level_max)
    )
    filters_ok = volume_ok and atr_ok and level_ok
    # Режим рынка по старшему ТФ: trend / range / surge; при surge можно блокировать вход
    regime_block_surge = getattr(config, "REGIME_BLOCK_SURGE", True)
    higher_tf_regime = higher_tf_data.get("regime", "range")
    regime_ok = (higher_tf_regime != "surge") or not regime_block_surge
    higher_tf_candle_quality_ok = higher_tf_data.get("candle_quality_ok", True)
    candle_quality_ok_global = (
        candle_quality_min <= 0 or (higher_tf_candle_quality_ok and all(
            (timeframes_report.get(_tf) or {}).get("candle_quality_ok", True)
            for _tf in sorted_tfs
        ))
    )
    # Сколько ТФ совпадают со старшим по тренду и поддерживают направление (бычья/медвежья фаза)
    tf_align_min = getattr(config, "TF_ALIGN_MIN", 1)
    tf_align_count = 0
    for _tf, _d in timeframes_report.items():
        if _d.get("trend") != higher_tf_trend:
            continue
        if higher_tf_trend == "up" and _d.get("phase") in BULLISH_PHASES:
            tf_align_count += 1
        elif higher_tf_trend == "down" and _d.get("phase") in BEARISH_PHASES:
            tf_align_count += 1
        elif higher_tf_trend == "flat":
            tf_align_count += 1
    tf_align_ok = tf_align_count >= tf_align_min
    higher_tf_trend_strength = higher_tf_data.get("trend_strength", 0.0)
    higher_tf_trend_unclear = higher_tf_data.get("trend_unclear", True)
    higher_tf_trend_stable = higher_tf_data.get("trend_stable", True)
    trend_stability_min = getattr(config, "TREND_STABILITY_MIN", 0.0)
    trend_stable_ok = trend_stability_min <= 0 or higher_tf_trend_stable
    higher_tf_phase = higher_tf_data.get("phase", "accumulation")
    higher_tf_phase_ru = higher_tf_data.get("phase_ru", "—")
    higher_tf_phase_score = higher_tf_data.get("phase_score", 0.0)
    higher_tf_phase_unclear = higher_tf_data.get("phase_unclear", True)
    higher_tf_phase_stable = higher_tf_data.get("phase_stable", False)
    higher_tf_score_gap = higher_tf_data.get("score_gap", 0.0)
    phase_score_min = getattr(config, "PHASE_SCORE_MIN", 0.6)
    phase_min_gap = getattr(config, "PHASE_MIN_GAP", 0.1)
    phase_ok = higher_tf_phase_score >= phase_score_min
    phase_decision_ready = (
        phase_ok
        and not higher_tf_phase_unclear
        and higher_tf_phase_stable
        and higher_tf_score_gap >= phase_min_gap
        and not higher_tf_trend_unclear
        and filters_ok
        and tf_align_ok
        and trend_stable_ok
        and regime_ok
        and candle_quality_ok_global
    )
    signal_min_conf = getattr(config, "SIGNAL_MIN_CONFIDENCE", 0.0)

    direction = "none"
    reason = f"старший ТФ {higher_tf}: {higher_tf_trend}, фаза {higher_tf_phase_ru}"
    if not phase_ok:
        reason = f"фаза {higher_tf_phase_ru} (score={higher_tf_phase_score:.2f} < {phase_score_min}) — не используем для входа"
    elif not phase_decision_ready:
        why = []
        if higher_tf_phase_unclear:
            why.append("фаза неясна")
        if not higher_tf_phase_stable:
            why.append("фаза неустойчива")
        if higher_tf_score_gap < phase_min_gap:
            why.append(f"разрыв score {higher_tf_score_gap:.2f} < {phase_min_gap}")
        if higher_tf_trend_unclear:
            why.append("тренд неясен")
        if not volume_ok:
            why.append("объём низкий")
        if not atr_ok:
            why.append("ATR высокий")
        if not level_ok:
            why.append("цена далеко от уровней")
        if not tf_align_ok:
            why.append(f"совпадение ТФ {tf_align_count} < {tf_align_min}")
        if not trend_stable_ok:
            why.append("тренд неустойчив")
        if not regime_ok:
            why.append("режим всплеск")
        if not candle_quality_ok_global:
            why.append("качество свечей")
        reason = f"фаза {higher_tf_phase_ru} — не готово к решению: {', '.join(why)}"
    elif phase_decision_ready and higher_tf_trend == "up":
        if higher_tf_phase in BULLISH_PHASES:
            direction = "long"
            reason = f"тренд на {higher_tf} вверх, фаза {higher_tf_phase_ru} — разрешён лонг"
        else:
            reason = f"тренд вверх, но фаза {higher_tf_phase_ru} не бычья — осторожно с лонгом"
    elif phase_decision_ready and higher_tf_trend == "down":
        if higher_tf_phase in BEARISH_PHASES:
            direction = "short"
            reason = f"тренд на {higher_tf} вниз, фаза {higher_tf_phase_ru} — разрешён шорт"
        else:
            reason = f"тренд вниз, но фаза {higher_tf_phase_ru} не медвежья — осторожно с шортом"

    # Единый score входа 0..1: взвешенная сумма фазы, тренда и совпадения ТФ
    w_phase = getattr(config, "ENTRY_SCORE_WEIGHT_PHASE", 0.4)
    w_trend = getattr(config, "ENTRY_SCORE_WEIGHT_TREND", 0.35)
    w_tf = getattr(config, "ENTRY_SCORE_WEIGHT_TF_ALIGN", 0.25)
    n_tfs = max(1, len(sorted_tfs))
    tf_align_ratio = tf_align_count / n_tfs
    weight_sum = w_phase + w_trend + w_tf
    if weight_sum <= 0:
        weight_sum = 1.0
    entry_score_raw = (
        w_phase * higher_tf_phase_score
        + w_trend * higher_tf_trend_strength
        + w_tf * tf_align_ratio
    ) / weight_sum
    stability_bonus = 0.0
    if higher_tf_phase_stable and higher_tf_trend_stable:
        stability_bonus = 0.05
    entry_score = min(1.0, entry_score_raw + stability_bonus)
    entry_score = max(0.0, round(entry_score, 3))

    # Уверенность сигнала 0..1: берём единый score входа при наличии направления, иначе 0
    confidence = entry_score if direction != "none" else 0.0
    if confidence >= 0.7:
        confidence_level = "strong"
    elif confidence >= 0.5:
        confidence_level = "medium"
    elif confidence > 0:
        confidence_level = "weak"
    else:
        confidence_level = "—"
    above_min = confidence >= signal_min_conf

    # Снимок «текущее состояние рынка» (prop-style): решение только по тому, что происходит сейчас на всех ТФ
    higher_tf_regime_ru = higher_tf_data.get("regime_ru", "—")
    mom_dir_ru = higher_tf_data.get("momentum_direction_ru", "—")
    in_zone = (trading_zones.get("in_zone") or False)
    at_sup = trading_zones.get("at_support_zone") or False
    at_res = trading_zones.get("at_resistance_zone") or False
    zone_parts = []
    if at_sup:
        zone_parts.append("у поддержки")
    if at_res:
        zone_parts.append("у сопротивления")
    if in_zone and not zone_parts:
        zone_parts.append("в зоне S–R")
    zone_str = ", ".join(zone_parts) if zone_parts else "вне ключевых зон"
    market_state_narrative = (
        f"Сейчас: старший ТФ — тренд {higher_tf_trend}, фаза {higher_tf_phase_ru}, режим {higher_tf_regime_ru}; "
        f"цена {zone_str}; импульс {mom_dir_ru}. Совпадение ТФ: {tf_align_count}/{len(sorted_tfs)}."
    )

    return {
        "symbol": symbol,
        "timeframes": timeframes_report,
        "higher_tf_trend": higher_tf_trend,
        "higher_tf_phase": higher_tf_phase,
        "higher_tf_phase_ru": higher_tf_phase_ru,
        "higher_tf_phase_score": higher_tf_phase_score,
        "signals": {
            "direction": direction,
            "reason": reason,
            "phase_ok": phase_ok,
            "phase_decision_ready": phase_decision_ready,
            "phase_score_min": phase_score_min,
            "entry_score": entry_score,
            "entry_score_breakdown": {
                "phase": higher_tf_phase_score,
                "trend": higher_tf_trend_strength,
                "tf_align_ratio": round(tf_align_ratio, 3),
                "stability_bonus": stability_bonus,
            },
            "confidence": round(confidence, 3),
            "confidence_level": confidence_level,
            "above_min_confidence": above_min,
        },
        "higher_tf_phase_unclear": higher_tf_data.get("phase_unclear", True),
        "higher_tf_phase_stable": higher_tf_data.get("phase_stable", False),
        "higher_tf_score_gap": higher_tf_data.get("score_gap", 0.0),
        "higher_tf_secondary_phase": higher_tf_data.get("secondary_phase"),
        "higher_tf_secondary_phase_ru": higher_tf_data.get("secondary_phase_ru"),
        "higher_tf_trend_strength": higher_tf_trend_strength,
        "higher_tf_trend_confidence": higher_tf_data.get("trend_confidence", 0.0),
        "higher_tf_trend_unclear": higher_tf_trend_unclear,
        "higher_tf_trend_ru": higher_tf_data.get("trend_ru", "—"),
        "higher_tf_secondary_trend_ru": higher_tf_data.get("secondary_trend_ru"),
        "higher_tf_trend_strength_gap": higher_tf_data.get("trend_strength_gap", 0.0),
        "higher_tf_trend_stable": higher_tf_trend_stable,
        "higher_tf_trend_stability": higher_tf_data.get("trend_stability", 0.0),
        "volume_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
        "volume_ok": volume_ok,
        "atr_ratio": round(atr_ratio, 3) if atr_ratio is not None else None,
        "atr_ok": atr_ok,
        "filters_ok": filters_ok,
        "swing_low": levels.get("swing_low"),
        "swing_high": levels.get("swing_high"),
        "distance_to_support_pct": dist_support,
        "distance_to_resistance_pct": dist_resistance,
        "level_ok": level_ok,
        "trading_zones": trading_zones,
        "higher_tf_rsi_bull_div": (higher_tf_data.get("phase_details") or {}).get("rsi_bullish_divergence", False),
        "higher_tf_rsi_bear_div": (higher_tf_data.get("phase_details") or {}).get("rsi_bearish_divergence", False),
        "tf_align_count": tf_align_count,
        "tf_align_min": tf_align_min,
        "tf_align_ok": tf_align_ok,
        "candle_quality_ok": candle_quality_ok_global,
        "higher_tf_candle_quality_score": higher_tf_data.get("candle_quality_score"),
        "entry_score": entry_score,
        "higher_tf_regime": higher_tf_regime,
        "higher_tf_regime_ru": higher_tf_data.get("regime_ru", "—"),
        "higher_tf_regime_adx": higher_tf_data.get("regime_adx"),
        "higher_tf_regime_atr_ratio": higher_tf_data.get("regime_atr_ratio"),
        "regime_ok": regime_ok,
        "higher_tf_momentum_state": higher_tf_data.get("momentum_state", "neutral"),
        "higher_tf_momentum_state_ru": higher_tf_data.get("momentum_state_ru", "Нейтральный"),
        "higher_tf_momentum_direction": higher_tf_data.get("momentum_direction", "neutral"),
        "higher_tf_momentum_direction_ru": higher_tf_data.get("momentum_direction_ru", "Нейтральный"),
        "higher_tf_momentum_rsi": higher_tf_data.get("momentum_rsi"),
        "higher_tf_momentum_return_5": higher_tf_data.get("momentum_return_5"),
        "market_state_narrative": market_state_narrative,
        "decision_basis": "current_snapshot",
    }


def analyze_multi_timeframe(
    symbol: str | None = None,
    intervals: list[str] | None = None,
    data_source: str | None = None,
    db_conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """
    Собирает данные по всем таймфреймам, тренды, 6 фаз и агрегированный сигнал.
    data_source: "db" | "exchange" | None (берётся из config.DATA_SOURCE).
    db_conn: при data_source="db" — соединение с БД; иначе используется биржа.
    """
    symbol = symbol or config.SYMBOL
    intervals = intervals or config.TIMEFRAMES
    if not intervals:
        return {
            "symbol": symbol,
            "timeframes": {},
            "higher_tf_trend": "flat",
            "signals": {"direction": "none", "reason": "no timeframes", "confidence": 0.0, "confidence_level": "—"},
        }
    src = (data_source or getattr(config, "DATA_SOURCE", "exchange") or "exchange").lower()
    if src == "db" and db_conn is not None:
        data = _load_candles_from_db(db_conn, symbol, intervals, limit=config.KLINE_LIMIT or 200)
    else:
        data = get_klines_multi_timeframe(symbol=symbol, intervals=intervals)
    return _compute_multi_tf_result(data, intervals, symbol)


def analyze_multi_timeframe_from_data(
    data_by_tf: dict[str, list[dict[str, Any]]],
    intervals: list[str] | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """
    Мультитаймфреймовый анализ по уже загруженным свечам (для бэктеста).
    data_by_tf[tf] = список свечей (от старых к новым), доступных на момент «сейчас».
    intervals — список ТФ для анализа; если None, берутся ключи data_by_tf.
    """
    symbol = symbol or config.SYMBOL
    intervals = intervals or list(data_by_tf.keys())
    if not intervals:
        return {
            "symbol": symbol,
            "timeframes": {},
            "higher_tf_trend": "flat",
            "signals": {"direction": "none", "reason": "no timeframes", "confidence": 0.0, "confidence_level": "—"},
        }
    return _compute_multi_tf_result(data_by_tf, intervals, symbol)
