"""
Один тик цикла торгового бота: обновление БД (если пора) + мультиТФ-анализ + лог результата.
Используется из main.py — там только цикл и пауза, вся логика «что делать за шаг» здесь.
При ORDERFLOW_ENABLED и переданных orderbook_stream/trades_stream добавляется анализ Order Flow (DOM, T&S, Delta, Sweeps).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from ..analysis.multi_tf import analyze_multi_timeframe
from ..core import config
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
    mom_state = report.get("higher_tf_momentum_state_ru") or "—"
    mom_dir = report.get("higher_tf_momentum_direction_ru") or "—"
    mom_rsi = report.get("higher_tf_momentum_rsi")
    logger.info(
        "  Старший ТФ импульс: %s (%s), направление=%s, RSI=%s",
        report.get("higher_tf_momentum_state", "neutral"),
        mom_state,
        mom_dir,
        mom_rsi if mom_rsi is not None else "—",
    )
    # Торговые зоны (уровни с переключением ролей: сопротивление → поддержка и наоборот)
    zones = report.get("trading_zones") or {}
    if zones.get("levels"):
        z_low = zones.get("zone_low")
        z_high = zones.get("zone_high")
        in_z = zones.get("in_zone", False)
        ns = zones.get("nearest_support")
        nr = zones.get("nearest_resistance")
        rf = zones.get("recent_flips") or []
        at_sup = zones.get("at_support_zone", False)
        at_res = zones.get("at_resistance_zone", False)
        levels_conf = zones.get("levels_with_confluence", 0)
        logger.info(
            "  Зоны: зона %s–%s, в_зоне=%s | у_поддержки=%s у_сопротивления=%s | конfluence_уровней=%s | поддержка=%s (%s) | сопротивление=%s (%s) | переворотов=%s",
            round(z_low, 2) if z_low is not None else "—",
            round(z_high, 2) if z_high is not None else "—",
            in_z,
            at_sup,
            at_res,
            levels_conf,
            round(ns["price"], 2) if ns else "—",
            (ns.get("origin_role") or "—") + ("→" + (ns.get("current_role") or "") if ns and ns.get("broken") else ""),
            round(nr["price"], 2) if nr else "—",
            (nr.get("origin_role") or "—") + ("→" + (nr.get("current_role") or "") if nr and nr.get("broken") else ""),
            len(rf),
        )
        for flip in rf[:3]:
            logger.info("    Переворот: %.2f было %s → стало %s", flip.get("price", 0), flip.get("origin_role", "—"), flip.get("current_role", "—"))
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
    # Order Flow (DOM, T&S, Delta, Sweeps) — при наличии
    of = report.get("orderflow") or {}
    if of:
        dom = of.get("dom") or {}
        delta = of.get("volume_delta") or {}
        sweeps = of.get("sweeps") or {}
        logger.info(
            "  Order Flow: DOM imbalance=%.2f | delta=%.2f (ratio=%.2f) | last_sweep=%s @ %s",
            dom.get("imbalance_ratio", 0.5),
            delta.get("delta", 0.0),
            delta.get("delta_ratio", 0.0),
            sweeps.get("last_sweep_side") or "—",
            sweeps.get("last_sweep_time") or "—",
        )
        absorption = of.get("absorption")
        if absorption:
            logger.info(
                "  Absorption: bid=%s ask=%s | bid_drop=%.2f ask_drop=%.2f | bullish=%s bearish=%s",
                absorption.get("absorption_bid", False),
                absorption.get("absorption_ask", False),
                absorption.get("bid_drop_ratio") or 0,
                absorption.get("ask_drop_ratio") or 0,
                absorption.get("absorption_bullish", False),
                absorption.get("absorption_bearish", False),
            )
        div = of.get("delta_price_divergence")
        if div:
            logger.info(
                "  Delta/price divergence: bearish=%s bullish=%s | first=%.2f last=%.2f delta_ratio=%.3f",
                div.get("bearish_divergence", False),
                div.get("bullish_divergence", False),
                div.get("first_price") or 0,
                div.get("last_price") or 0,
                div.get("delta_ratio") or 0,
            )
    # Контекст «здесь и сейчас» (уровень + flow за короткое окно)
    ctx = report.get("context_now")
    if ctx:
        logger.info(
            "  Context now: at_support=%s at_resistance=%s | flow_bullish=%s flow_bearish=%s | absorption_bull=%s absorption_bear=%s | short_delta_ratio=%.3f | allowed_long=%s allowed_short=%s",
            ctx.get("at_support"), ctx.get("at_resistance"),
            ctx.get("flow_bullish_now"), ctx.get("flow_bearish_now"),
            ctx.get("absorption_bullish"), ctx.get("absorption_bearish"),
            ctx.get("short_window_delta_ratio", 0),
            ctx.get("allowed_long"), ctx.get("allowed_short"),
        )
    # Песочница микроструктуры (виртуальная позиция и PnL)
    sandbox_state = report.get("microstructure_sandbox")
    if sandbox_state:
        logger.info(
            "  Песочница микроструктуры: позиция=%s | entry=%.2f | realized=$%.2f | комиссия=$%.2f | unrealized=$%.2f | эквити=$%.2f | сделок=%s | сигнал=%s (%.2f)",
            sandbox_state.get("position_side", "—"),
            sandbox_state.get("entry_price", 0),
            sandbox_state.get("total_realized_pnl", 0),
            sandbox_state.get("total_commission", 0),
            sandbox_state.get("unrealized_pnl", 0),
            sandbox_state.get("equity_usd", 0),
            sandbox_state.get("trades_count", 0),
            sandbox_state.get("last_signal_direction", "—"),
            sandbox_state.get("last_signal_confidence", 0),
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


def _orderflow_candles_for_sweep(db_conn: sqlite3.Connection | None, lookback_bars: int = 10) -> list[dict[str, Any]]:
    """Последние lookback_bars свечей по младшему ТФ из TIMEFRAMES_DB для detect_sweeps. Порядок: от старых к новым."""
    if not db_conn or not config.TIMEFRAMES_DB:
        return []
    try:
        from ..core.database import get_candles
        # Младший ТФ — первый в списке (1, 3, 5, 15, ...)
        min_tf = config.TIMEFRAMES_DB[0]
        cursor = db_conn.cursor()
        rows = get_candles(cursor, config.SYMBOL, min_tf, limit=lookback_bars, order_asc=False)
        return list(reversed(rows))  # от старых к новым
    except Exception:
        return []


def run_one_tick(
    db_conn: sqlite3.Connection | None,
    last_db_ts: float,
    *,
    orderbook_stream: Any = None,
    trades_stream: Any = None,
    microstructure_sandbox: Any = None,
    last_orderbook_snapshot: list | None = None,
) -> float:
    """
    Один проход цикла: обновить БД по таймеру, выполнить анализ, залогировать.
    При ORDERFLOW_ENABLED и переданных orderbook_stream/trades_stream добавляется Order Flow (DOM, T&S, Delta, Sweeps).
    При last_orderbook_snapshot (список из одного элемента) — анализ поглощения (стакан до/после); после тика в [0] пишется текущий снимок.
    При microstructure_sandbox — обновляется виртуальная позиция по сигналу микроструктуры, результат в report.
    Возвращает актуальную метку времени последнего обновления БД.
    """
    last_db_ts = refresh_if_due(db_conn, last_db_ts)
    report = analyze_multi_timeframe(db_conn=db_conn)

    if getattr(config, "ORDERFLOW_ENABLED", False) and (orderbook_stream or trades_stream):
        try:
            from ..analysis.orderflow import analyze_orderflow, analyze_absorption, enrich_absorption_with_block
            from .microstructure_sandbox import _mid_from_snapshot
            orderbook_snapshot = orderbook_stream.get_snapshot() if orderbook_stream else None
            window_sec = getattr(config, "ORDERFLOW_WINDOW_SEC", 60.0)
            short_window_sec = float(getattr(config, "ORDERFLOW_SHORT_WINDOW_SEC", 0) or 0)
            now_ms = int(time.time() * 1000)
            recent_trades = (
                trades_stream.get_recent_trades_since(now_ms - int(max(window_sec, short_window_sec or 0) * 1000))
                if trades_stream
                else []
            )
            candles_for_sweep = _orderflow_candles_for_sweep(db_conn, lookback_bars=10)
            of_result = analyze_orderflow(
                orderbook_snapshot=orderbook_snapshot,
                recent_trades=recent_trades if recent_trades else None,
                candles=candles_for_sweep if candles_for_sweep else None,
                window_sec=window_sec,
                short_window_sec=short_window_sec,
                now_ts_ms=now_ms,
                last_trades_k=10,
            )
            report["orderflow"] = of_result
            # Поглощение: сравнение стакана до/после (при передаче last_orderbook_snapshot)
            if last_orderbook_snapshot is not None and len(last_orderbook_snapshot) > 0 and orderbook_snapshot:
                prev_snap = last_orderbook_snapshot[0]
                absorption = analyze_absorption(
                    prev_snap,
                    orderbook_snapshot,
                    depth_levels=20,
                    min_drop_ratio=0.7,
                )
                of_result["absorption"] = absorption
                enrich_absorption_with_block(of_result["absorption"], of_result.get("last_trades"))
            else:
                of_result["absorption"] = None
            if orderbook_snapshot and last_orderbook_snapshot is not None and len(last_orderbook_snapshot) > 0:
                last_orderbook_snapshot[0] = orderbook_snapshot
            mid = _mid_from_snapshot(orderbook_snapshot) if orderbook_snapshot else None
            if of_result and mid is not None and mid > 0:
                try:
                    from ..analysis.context_now import compute_context_now
                    level_pct = float(getattr(config, "CONTEXT_NOW_LEVEL_DISTANCE_PCT", 0.0015) or 0.0015)
                    delta_min = float(getattr(config, "CONTEXT_NOW_DELTA_RATIO_MIN", 0.12) or 0.12)
                    use_dom_levels = bool(getattr(config, "CONTEXT_NOW_USE_DOM_LEVELS", False))
                    report["context_now"] = compute_context_now(
                        mid, of_result, report.get("trading_zones"),
                        level_distance_pct=level_pct,
                        delta_ratio_min=delta_min,
                        use_dom_levels=use_dom_levels,
                    )
                except Exception as e:
                    logger.debug("context_now пропущен: %s", e)
                    report["context_now"] = None
            else:
                report["context_now"] = None
            if getattr(config, "ORDERFLOW_SAVE_TO_DB", False) and db_conn and of_result:
                try:
                    from ..core.database import insert_orderflow_metrics
                    cur = db_conn.cursor()
                    insert_orderflow_metrics(cur, config.SYMBOL, int(time.time()), of_result)
                    db_conn.commit()
                except Exception as e:
                    logger.debug("Order Flow запись в БД пропущена: %s", e)
            # Песочница микроструктуры: виртуальная позиция и PnL по сигналу
            if microstructure_sandbox is not None and orderbook_snapshot and of_result and mid is not None:
                try:
                    higher_tf_trend = report.get("higher_tf_trend") or None
                    context_now = report.get("context_now")
                    state = microstructure_sandbox.update(
                        of_result, mid, int(time.time()),
                        higher_tf_trend=higher_tf_trend,
                        context_now=context_now,
                    )
                    report["microstructure_sandbox"] = state
                    from . import sandbox_state
                    sandbox_state.set_last_state(state)
                except Exception as e:
                    logger.debug("Песочница микроструктуры пропущена: %s", e)
        except Exception as e:
            logger.debug("Order Flow анализ пропущен: %s", e)

    _log_report(report)
    return last_db_ts
