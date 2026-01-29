"""
Один тик цикла торгового бота: обновление БД (если пора) + мультиТФ-анализ + лог результата.
Используется из main.py — там только цикл и пауза, вся логика «что делать за шаг» здесь.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from ..analysis.multi_tf import analyze_multi_timeframe
from .db_sync import refresh_if_due

logger = logging.getLogger(__name__)


def _log_report(report: dict[str, Any]) -> None:
    """Пишет в лог результат мультиТФ-анализа и одну компактную строку в signals.log."""
    direction = report["signals"].get("direction", "?")
    reason = report["signals"].get("reason", "")
    higher_trend = report.get("higher_tf_trend", "?")
    higher_phase = report.get("higher_tf_phase_ru", "—")
    phase_decision_ready = report["signals"].get("phase_decision_ready", False)
    logger.info(
        "Сигнал: %s | Старший ТФ: тренд=%s, фаза=%s | готов к решению=%s",
        direction,
        higher_trend,
        higher_phase,
        phase_decision_ready,
    )
    logger.info("  Причина: %s", reason)
    # Метрики определения фазы по старшему ТФ
    unclear = report.get("higher_tf_phase_unclear", True)
    secondary_ru = report.get("higher_tf_secondary_phase_ru") or "—"
    score_gap = report.get("higher_tf_score_gap", 0.0)
    stable = report.get("higher_tf_phase_stable", False)
    logger.info(
        "  Старший ТФ: фаза неясна=%s, вторая фаза=%s, разрыв score=%.2f, устойчивость=%s",
        unclear,
        secondary_ru,
        score_gap,
        stable,
    )
    # Метрики тренда по старшему ТФ
    trend_strength = report.get("higher_tf_trend_strength", 0.0)
    trend_confidence = report.get("higher_tf_trend_confidence", 0.0)
    trend_unclear = report.get("higher_tf_trend_unclear", True)
    trend_ru = report.get("higher_tf_trend_ru") or "—"
    secondary_trend_ru = report.get("higher_tf_secondary_trend_ru") or "—"
    trend_gap = report.get("higher_tf_trend_strength_gap", 0.0)
    logger.info(
        "  Старший ТФ тренд: %s, сила=%.2f, уверенность=%.0f%%, неясен=%s, вторая=%s, разрыв=%.2f",
        trend_ru,
        trend_strength,
        trend_confidence * 100,
        trend_unclear,
        secondary_trend_ru,
        trend_gap,
    )
    regime_ru = report.get("higher_tf_regime_ru") or "—"
    regime_adx = report.get("higher_tf_regime_adx")
    regime_atr = report.get("higher_tf_regime_atr_ratio")
    regime_ok = report.get("regime_ok", True)
    logger.info(
        "  Старший ТФ режим: %s (ADX=%s, ATR_ratio=%s), regime_ok=%s",
        regime_ru,
        regime_adx if regime_adx is not None else "—",
        regime_atr if regime_atr is not None else "—",
        regime_ok,
    )
    for tf, data in report.get("timeframes", {}).items():
        trend = data.get("trend", "?")
        trend_str = data.get("trend_strength", 0.0)
        trend_conf = data.get("trend_confidence", 0.0)
        phase_ru = data.get("phase_ru", "—")
        n = len(data.get("candles", []))
        sec = data.get("secondary_phase_ru") or "—"
        gap = data.get("score_gap", 0.0)
        st = data.get("phase_stable", False)
        reg_ru = data.get("regime_ru") or "—"
        q_ok = data.get("candle_quality_ok", True)
        q_sc = data.get("candle_quality_score")
        q_str = f" quality={q_sc}" if q_sc is not None else ""
        logger.info(
            "  ТФ %s: тренд=%s (сила=%.2f, уверенность=%.0f%%), фаза=%s, режим=%s, свечей=%s%s | вторая=%s, gap=%.2f, stable=%s",
            tf, trend, trend_str, trend_conf * 100, phase_ru, reg_ru, n, q_str, sec, gap, st,
        )
    entry_score = report["signals"].get("entry_score")
    conf = report["signals"].get("confidence", 0)
    conf_lvl = report["signals"].get("confidence_level", "—")
    candle_quality_ok = report.get("candle_quality_ok", True)
    higher_tf_quality = report.get("higher_tf_candle_quality_score")
    logger.info(
        "  Единый score входа: %s | уверенность: %s (%s) | качество свечей: %s (старший ТФ score=%s)",
        entry_score if entry_score is not None else "—",
        conf,
        conf_lvl,
        candle_quality_ok,
        higher_tf_quality if higher_tf_quality is not None else "—",
    )
    # Компактная строка в signals.log для разбора и статистики
    try:
        from ..core.logging_config import get_signals_logger
        sig = get_signals_logger()
        sig.info(
            "direction=%s | entry_score=%s | confidence=%s | %s | phase_ready=%s | reason=%s | higher_tf_trend=%s | higher_tf_phase=%s | gap=%.2f",
            direction, entry_score, conf, conf_lvl, phase_decision_ready, reason, higher_trend, higher_phase, score_gap,
        )
    except Exception:  # не ломаем тик из-за логгера
        pass


def run_one_tick(db_conn: sqlite3.Connection | None, last_db_ts: float) -> float:
    """
    Один проход цикла: обновить БД по таймеру, выполнить анализ, залогировать.
    Возвращает актуальную метку времени последнего обновления БД.
    """
    last_db_ts = refresh_if_due(db_conn, last_db_ts)
    report = analyze_multi_timeframe(db_conn=db_conn)
    _log_report(report)
    return last_db_ts
