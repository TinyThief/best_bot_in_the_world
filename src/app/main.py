"""
Точка входа мультитаймфреймового торгового бота для Bybit.
Только цикл и запуск: конфиг, подготовка БД, вызов bot_loop.run_one_tick, пауза, завершение.
Telegram-бот (если задан TELEGRAM_BOT_TOKEN) запускается в отдельном потоке и использует то же соединение с БД.
"""
import asyncio
import logging
import threading
import time

from ..core import config
from ..core.config import validate_config
from ..core.logging_config import setup_logging
from .bot_loop import run_one_tick
from .db_sync import close, open_and_prepare

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    errs = validate_config()
    if errs:
        for e in errs:
            logger.warning("Конфиг: %s", e)
        logger.info("Запуск в режиме только чтения (без сделок)")

    db_conn = open_and_prepare()
    if db_conn is not None:
        logger.info(
            "БД будет обновляться каждые %s с",
            config.DB_UPDATE_INTERVAL_SEC,
        )
    else:
        logger.info("TIMEFRAMES_DB пуст — обновление БД отключено")

    telegram_thread = None
    if config.TELEGRAM_BOT_TOKEN:
        from .telegram_bot import run_bot

        def _run_telegram_in_thread(db_conn):
            # В новом потоке нет event loop; APScheduler/python-telegram-bot вызывают get_event_loop().
            asyncio.set_event_loop(asyncio.new_event_loop())
            run_bot(db_conn=db_conn)

        telegram_thread = threading.Thread(
            target=_run_telegram_in_thread,
            kwargs={"db_conn": db_conn},
            daemon=True,
        )
        telegram_thread.start()
        logger.info("Telegram-бот запущен от основного бота (общее соединение с БД)")

    orderbook_stream = None
    trades_stream = None
    microstructure_sandbox = None
    if getattr(config, "ORDERFLOW_ENABLED", False):
        try:
            from ..core.orderbook_ws import OrderbookStream
            from ..core.trades_ws import TradesStream
            orderbook_stream = OrderbookStream()
            trades_stream = TradesStream()
            orderbook_stream.start()
            trades_stream.start()
            logger.info("Order Flow включён: стакан и поток сделок запущены")
            if getattr(config, "MICROSTRUCTURE_SANDBOX_ENABLED", False):
                from .microstructure_sandbox import MicrostructureSandbox
                initial_usd = float(getattr(config, "SANDBOX_INITIAL_BALANCE", 100) or 100)
                taker_fee = float(getattr(config, "SANDBOX_TAKER_FEE", 0.0006) or 0.0006)
                min_conf = float(getattr(config, "SANDBOX_MIN_CONFIDENCE", 0.4) or 0)
                cooldown = int(getattr(config, "SANDBOX_COOLDOWN_SEC", 60) or 0)
                min_hold = int(getattr(config, "SANDBOX_MIN_HOLD_SEC", 90) or 0)
                exit_ticks = int(getattr(config, "SANDBOX_EXIT_NONE_TICKS", 2) or 1)
                exit_min_conf = float(getattr(config, "SANDBOX_EXIT_MIN_CONFIDENCE", 0) or 0)
                min_confirming = int(getattr(config, "SANDBOX_MIN_CONFIRMING_TICKS", 0) or 0)
                exit_win = int(getattr(config, "SANDBOX_EXIT_WINDOW_TICKS", 0) or 0)
                exit_win_need = int(getattr(config, "SANDBOX_EXIT_WINDOW_NEED", 0) or 0)
                stop_pct = float(getattr(config, "SANDBOX_STOP_LOSS_PCT", 0) or 0)
                breakeven_trigger_pct = float(getattr(config, "SANDBOX_BREAKEVEN_TRIGGER_PCT", 0) or 0)
                take_pct = float(getattr(config, "SANDBOX_TAKE_PROFIT_PCT", 0) or 0)
                tp_levels_raw = (getattr(config, "SANDBOX_TP_LEVELS", None) or "").strip()
                trail_trigger_pct = float(getattr(config, "SANDBOX_TRAIL_TRIGGER_PCT", 0) or 0)
                trail_pct = float(getattr(config, "SANDBOX_TRAIL_PCT", 0) or 0)
                take_profit_levels: list[tuple[float, float]] = []
                if tp_levels_raw:
                    cumulative = 0.0
                    for part in tp_levels_raw.split(","):
                        part = part.strip()
                        if ":" in part:
                            a, b = part.split(":", 1)
                            try:
                                pct = float(a.strip())
                                share_pct = float(b.strip())
                                if 0 < share_pct <= 100 and pct > 0:
                                    cumulative += share_pct / 100.0
                                    take_profit_levels.append((pct, min(1.0, cumulative)))
                            except (ValueError, TypeError):
                                pass
                    take_profit_levels.sort(key=lambda x: x[0])
                trend_filt = bool(getattr(config, "SANDBOX_TREND_FILTER", False))
                lev_min = float(getattr(config, "SANDBOX_LEVERAGE_MIN", 1) or 1)
                lev_max = float(getattr(config, "SANDBOX_LEVERAGE_MAX", 5) or 5)
                adaptive_lev = bool(getattr(config, "SANDBOX_ADAPTIVE_LEVERAGE", True))
                margin_frac = float(getattr(config, "SANDBOX_MARGIN_FRACTION", 0.95) or 0.95)
                liq_maint = float(getattr(config, "SANDBOX_LIQUIDATION_MAINTENANCE", 1) or 1)
                dd_lev_pct = float(getattr(config, "SANDBOX_DRAWDOWN_LEVERAGE_PCT", 10) or 10)
                min_profit_pct = float(getattr(config, "SANDBOX_MIN_PROFIT_PCT", 0.15) or 0)
                no_open_same_tick = bool(getattr(config, "SANDBOX_NO_OPEN_SAME_TICK_AS_CLOSE", True))
                no_open_sweep_only = bool(getattr(config, "SANDBOX_NO_OPEN_SWEEP_ONLY", True))
                sweep_delay_sec = int(getattr(config, "SANDBOX_SWEEP_DELAY_SEC", 0) or 0)
                use_context_now_primary = bool(getattr(config, "SANDBOX_USE_CONTEXT_NOW_PRIMARY", False))
                use_context_now_only = bool(getattr(config, "SANDBOX_CONTEXT_NOW_ONLY", False))
                microstructure_sandbox = MicrostructureSandbox(
                    initial_balance=initial_usd,
                    taker_fee=taker_fee,
                    min_confidence_to_open=min_conf,
                    cooldown_sec=cooldown,
                    min_hold_sec=min_hold,
                    exit_none_ticks=exit_ticks,
                    exit_min_confidence=exit_min_conf,
                    min_confirming_ticks=min_confirming,
                    exit_window_ticks=exit_win,
                    exit_window_need=exit_win_need,
                    stop_loss_pct=stop_pct,
                    breakeven_trigger_pct=breakeven_trigger_pct,
                    take_profit_pct=take_pct,
                    take_profit_levels=take_profit_levels if take_profit_levels else None,
                    trail_trigger_pct=trail_trigger_pct,
                    trail_pct=trail_pct,
                    trend_filter=trend_filt,
                    leverage_min=lev_min,
                    leverage_max=lev_max,
                    adaptive_leverage=adaptive_lev,
                    margin_fraction=margin_frac,
                    liquidation_maintenance=liq_maint,
                    drawdown_leverage_pct=dd_lev_pct,
                    min_profit_pct=min_profit_pct,
                    no_open_same_tick_as_close=no_open_same_tick,
                    no_open_sweep_only=no_open_sweep_only,
                    sweep_delay_sec=sweep_delay_sec,
                    use_context_now_primary=use_context_now_primary,
                    use_context_now_only=use_context_now_only,
                )
                logger.info(
                    "Песочница микроструктуры включена: $%.0f баланс, комиссия %.4f%%, плечо %.1f–%.1f (адапт=%s), маржа=%.0f%%, ликвидация=%.2f, просадка_плечо=%.0f%%, вход conf>=%.2f, кулдаун=%s с, мин. удержание=%s с, sweep_only=%s, sweep_delay=%s с, context_now_primary=%s, context_now_only=%s",
                    initial_usd, taker_fee * 100, lev_min, lev_max, adaptive_lev, margin_frac * 100, liq_maint, dd_lev_pct, min_conf, cooldown, min_hold, no_open_sweep_only, sweep_delay_sec, use_context_now_primary, use_context_now_only,
                )
        except Exception as e:
            logger.warning("Order Flow не запущен: %s", e)

    # Интервал: проп-режим (CONTEXT_NOW_ONLY) → 5 с, иначе Order Flow → 15 с, иначе базовый
    context_now_only = getattr(config, "SANDBOX_CONTEXT_NOW_ONLY", False)
    orderflow_active = getattr(config, "ORDERFLOW_ENABLED", False) and (orderbook_stream is not None or microstructure_sandbox is not None)
    poll_sec = (
        (getattr(config, "POLL_INTERVAL_PROP_SEC", 5.0) or config.POLL_INTERVAL_SEC)
        if context_now_only and orderflow_active
        else (
            (getattr(config, "POLL_INTERVAL_ORDERFLOW_SEC", 15.0) or config.POLL_INTERVAL_SEC)
            if orderflow_active
            else config.POLL_INTERVAL_SEC
        )
    )
    logger.info(
        "Старт бота | пара=%s | таймфреймы=%s | интервал опроса=%s с",
        config.SYMBOL,
        config.TIMEFRAMES,
        poll_sec,
    )

    # Снимок стакана для анализа поглощения (до/после тика); мутабельный контейнер
    last_orderbook_snapshot: list = [None]
    # 0 — чтобы первый тик сразу обновил БД (догрузка до текущей даты), дальше по таймеру
    last_db_ts = 0.0
    try:
        while True:
            last_db_ts = run_one_tick(
                db_conn,
                last_db_ts,
                orderbook_stream=orderbook_stream,
                trades_stream=trades_stream,
                microstructure_sandbox=microstructure_sandbox,
                last_orderbook_snapshot=last_orderbook_snapshot if orderbook_stream else None,
            )
            context_now_only = getattr(config, "SANDBOX_CONTEXT_NOW_ONLY", False)
            orderflow_active = orderbook_stream is not None or microstructure_sandbox is not None
            poll_sec = (
                (getattr(config, "POLL_INTERVAL_PROP_SEC", 5.0) or config.POLL_INTERVAL_SEC)
                if context_now_only and orderflow_active
                else (
                    (getattr(config, "POLL_INTERVAL_ORDERFLOW_SEC", 15.0) or config.POLL_INTERVAL_SEC)
                    if orderflow_active
                    else config.POLL_INTERVAL_SEC
                )
            )
            time.sleep(poll_sec)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")
    finally:
        # Итог песочницы микроструктуры до остановки потоков (нужен стакан для mid)
        if microstructure_sandbox is not None and orderbook_stream is not None:
            try:
                from .microstructure_sandbox import _mid_from_snapshot
                snap = orderbook_stream.get_snapshot()
                mid = _mid_from_snapshot(snap) if snap else None
                if mid is None or mid <= 0:
                    mid = 0.0
                state = microstructure_sandbox.get_state()
                summary = microstructure_sandbox.get_summary(mid)
                unrealized = microstructure_sandbox.unrealized_pnl(mid)
                equity = microstructure_sandbox.equity(mid)
                logger.info(
                    "Итог песочницы микроструктуры: позиция=%s | старт=$%.0f | реализовано=$%.2f | комиссия=$%.2f | нереализовано=$%.2f | эквити=$%.2f | сделок=%s",
                    state.get("position_side", "—"),
                    microstructure_sandbox.initial_balance,
                    microstructure_sandbox.total_realized_pnl,
                    microstructure_sandbox.total_commission,
                    unrealized,
                    equity,
                    summary.get("trades_count", 0),
                )
                trades_list = getattr(microstructure_sandbox, "trades", [])
                for i, t in enumerate(trades_list, 1):
                    action = t.get("action", "")
                    side = t.get("side", "")
                    ts_utc = t.get("ts_utc", "")
                    price = t.get("price", "")
                    notional = t.get("notional_usd", "")
                    comm = t.get("commission_usd", "")
                    pnl = t.get("realized_pnl_usd", "")
                    if action == "open":
                        logger.info("  Песочница сделка #%s: %s %s %s | price=%s notional=$%s commission=$%s", i, ts_utc, action, side, price, notional, comm)
                    else:
                        logger.info("  Песочница сделка #%s: %s %s %s | price=%s realized=$%s commission=$%s", i, ts_utc, action, side, price, pnl, comm)
                from pathlib import Path
                from datetime import datetime
                log_dir = getattr(config, "LOG_DIR", None) or Path(__file__).resolve().parents[2] / "logs"
                if isinstance(log_dir, str):
                    log_dir = Path(log_dir)
                log_dir.mkdir(parents=True, exist_ok=True)
                result_path = log_dir / "sandbox_result.txt"
                with open(result_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"[{datetime.utcnow().isoformat()}Z] "
                        f"позиция={state.get('position_side')} | старт=${microstructure_sandbox.initial_balance:.0f} | "
                        f"реализовано=${microstructure_sandbox.total_realized_pnl:.2f} | комиссия=${microstructure_sandbox.total_commission:.2f} | "
                        f"нереализовано=${unrealized:.2f} | эквити=${equity:.2f} | "
                        f"сделок={summary.get('trades_count', 0)} | входов={summary.get('opens_count', 0)} | выходов={summary.get('closes_count', 0)} | "
                        f"в плюс={summary.get('winning_trades', 0)} | в минус={summary.get('losing_trades', 0)}\n"
                    )
                    exits_by = summary.get("exits_by") or {}
                    exits_parts = [f"{k}={v}" for k, v in sorted(exits_by.items())]
                    if exits_parts:
                        f.write("exits: " + ", ".join(exits_parts) + "\n")
                    # Список сделок для анализа
                    trades = getattr(microstructure_sandbox, "trades", [])
                    if trades:
                        f.write("--- Сделки ---\n")
                        for i, t in enumerate(trades, 1):
                            action = t.get("action", "")
                            side = t.get("side", "")
                            ts_utc = t.get("ts_utc", "")
                            price = t.get("price", "")
                            size = t.get("size", "")
                            notional = t.get("notional_usd", "")
                            comm = t.get("commission_usd", "")
                            pnl = t.get("realized_pnl_usd", "")
                            reason = (t.get("reason") or "")[:80]
                            exit_reason = (t.get("exit_reason") or "").strip()
                            if action == "open":
                                line = f"  #{i} {ts_utc}  {action:5} {side:5}  price={price}  size={size}  notional=${notional}  commission=${comm}"
                                if (t.get("entry_type") or "").strip():
                                    line += f"  | entry_type={t.get('entry_type')}"
                            else:
                                line = f"  #{i} {ts_utc}  {action:5} {side:5}  price={price}  realized=${pnl}  commission=${comm}"
                                if exit_reason:
                                    line += f"  | exit={exit_reason}"
                            if reason:
                                line += f"  | {reason}"
                            f.write(line + "\n")
                        f.write("\n")
                # Одна строка в sandbox_sessions.csv для сравнения сессий и связи результата с настройками
                import csv as csv_module
                session_end_utc = datetime.utcnow()
                session_start_utc = session_end_utc
                if trades_list:
                    first_ts = min(t.get("ts_unix") for t in trades_list if t.get("ts_unix"))
                    session_start_utc = datetime.utcfromtimestamp(first_ts)
                duration_min = (session_end_utc - session_start_utc).total_seconds() / 60.0 if trades_list else 0.0
                exits_by = summary.get("exits_by") or {}
                sessions_headers = [
                    "session_start_utc", "session_end_utc", "duration_min",
                    "initial_balance", "final_equity", "net_pnl", "total_commission",
                    "trades_count", "opens", "closes", "wins", "losses",
                    "exits_stop_loss", "exits_breakeven", "exits_take_profit", "exits_take_profit_part",
                    "exits_trailing_stop", "exits_microstructure", "exits_liquidation",
                    "sandbox_cooldown_sec", "sandbox_min_confidence", "sandbox_stop_loss_pct",
                    "sandbox_breakeven_trigger_pct", "sandbox_take_profit_pct", "sandbox_tp_levels",
                    "sandbox_trail_trigger_pct", "sandbox_trail_pct",
                ]
                sessions_path = log_dir / "sandbox_sessions.csv"
                sessions_row = {
                    "session_start_utc": session_start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    "session_end_utc": session_end_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration_min": round(duration_min, 1),
                    "initial_balance": microstructure_sandbox.initial_balance,
                    "final_equity": round(equity, 2),
                    "net_pnl": round(microstructure_sandbox.total_realized_pnl - microstructure_sandbox.total_commission, 2),
                    "total_commission": round(microstructure_sandbox.total_commission, 2),
                    "trades_count": summary.get("trades_count", 0),
                    "opens": summary.get("opens_count", 0),
                    "closes": summary.get("closes_count", 0),
                    "wins": summary.get("winning_trades", 0),
                    "losses": summary.get("losing_trades", 0),
                    "exits_stop_loss": exits_by.get("stop_loss", 0),
                    "exits_breakeven": exits_by.get("breakeven", 0),
                    "exits_take_profit": exits_by.get("take_profit", 0),
                    "exits_take_profit_part": exits_by.get("take_profit_part", 0),
                    "exits_trailing_stop": exits_by.get("trailing_stop", 0),
                    "exits_microstructure": exits_by.get("microstructure", 0),
                    "exits_liquidation": exits_by.get("liquidation", 0),
                    "sandbox_cooldown_sec": getattr(config, "SANDBOX_COOLDOWN_SEC", 0),
                    "sandbox_min_confidence": getattr(config, "SANDBOX_MIN_CONFIDENCE", 0),
                    "sandbox_stop_loss_pct": getattr(config, "SANDBOX_STOP_LOSS_PCT", 0),
                    "sandbox_breakeven_trigger_pct": getattr(config, "SANDBOX_BREAKEVEN_TRIGGER_PCT", 0),
                    "sandbox_take_profit_pct": getattr(config, "SANDBOX_TAKE_PROFIT_PCT", 0),
                    "sandbox_tp_levels": (getattr(config, "SANDBOX_TP_LEVELS", None) or "")[:50],
                    "sandbox_trail_trigger_pct": getattr(config, "SANDBOX_TRAIL_TRIGGER_PCT", 0),
                    "sandbox_trail_pct": getattr(config, "SANDBOX_TRAIL_PCT", 0),
                }
                try:
                    file_exists = sessions_path.exists()
                    with open(sessions_path, "a", newline="", encoding="utf-8") as sf:
                        w = csv_module.DictWriter(sf, fieldnames=sessions_headers)
                        if not file_exists:
                            w.writeheader()
                        w.writerow(sessions_row)
                except Exception as sess_e:
                    logger.debug("Не удалось записать сессию в %s: %s", sessions_path, sess_e)
                logger.info("Результат песочницы записан в %s (сводка + %s сделок), детали в logs/sandbox_trades.csv", result_path, len(getattr(microstructure_sandbox, "trades", [])))
            except Exception as e:
                logger.debug("Итог песочницы не записан: %s", e)
        if orderbook_stream is not None:
            try:
                orderbook_stream.stop()
            except Exception:
                pass
        if trades_stream is not None:
            try:
                trades_stream.stop()
            except Exception:
                pass
        close(db_conn)


if __name__ == "__main__":
    main()
