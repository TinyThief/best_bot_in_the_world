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
    logger.info(
        "Сигнал: %s | Старший ТФ: тренд=%s, фаза=%s",
        direction,
        higher_trend,
        higher_phase,
    )
    logger.info("  Причина: %s", reason)
    for tf, data in report.get("timeframes", {}).items():
        trend = data.get("trend", "?")
        phase_ru = data.get("phase_ru", "—")
        n = len(data.get("candles", []))
        logger.info("  ТФ %s: тренд=%s, фаза=%s, свечей=%s", tf, trend, phase_ru, n)
    # Компактная строка в signals.log для разбора и статистики
    try:
        from ..core.logging_config import get_signals_logger
        sig = get_signals_logger()
        sig.info(
            "direction=%s | reason=%s | higher_tf_trend=%s | higher_tf_phase=%s",
            direction, reason, higher_trend, higher_phase,
        )
    except Exception:  # не ломаем тик из-за логгера
        pass


def run_one_tick(db_conn: sqlite3.Connection | None, last_db_ts: float) -> float:
    """
    Один проход цикла: обновить БД по таймеру, выполнить анализ, залогировать.
    Возвращает актуальную метку времени последнего обновления БД.
    """
    last_db_ts = refresh_if_due(db_conn, last_db_ts)
    report = analyze_multi_timeframe()
    _log_report(report)
    return last_db_ts
