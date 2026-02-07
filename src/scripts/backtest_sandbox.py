"""
Бэктест песочницы микроструктуры по историческим тикам из data/history/trades/{symbol}/.

Реплей тиков по датам: скользящее окно сделок → синтетический стакан из дельты → analyze_orderflow
→ compute_microstructure_signal → MicrostructureSandbox.update(). Без реального стакана и без
старшего ТФ, поэтому DOM и context_now упрощены (imbalance из delta, context_now=None).

Пройденные диапазоны сохраняются в logs/sandbox_backtest_completed.json; повторный запуск
для уже пройденного диапазона пропускается (опция --force отключает проверку).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import time

from ..analysis.market_trend import detect_trend
from ..analysis.orderflow import analyze_orderflow, compute_volume_delta
from ..app.microstructure_sandbox import MicrostructureSandbox
from ..core import config
from ..core.database import (
    delete_incomplete_sandbox_runs,
    get_candles_before,
    get_connection,
    insert_sandbox_run,
    update_sandbox_run_finished,
)
from ..history import iter_trades

logger = logging.getLogger(__name__)

DEFAULT_TICK_SEC = 15
DEFAULT_WINDOW_SEC = 60.0
COMPLETED_RANGES_FILENAME = "sandbox_backtest_completed.json"


def _completed_ranges_path() -> Path:
    return Path(config.LOG_DIR) / COMPLETED_RANGES_FILENAME


def _load_completed_ranges() -> dict[str, list[tuple[str, str]]]:
    """Загружает сохранённые диапазоны: {symbol: [(from, to), ...]}."""
    path = _completed_ranges_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        by_symbol = raw.get("ranges") if "ranges" in raw else raw
        if not isinstance(by_symbol, dict):
            return {}
        out: dict[str, list[tuple[str, str]]] = {}
        for sym, ranges in by_symbol.items():
            if isinstance(ranges, list):
                out[str(sym)] = [tuple(r) for r in ranges if isinstance(r, (list, tuple)) and len(r) >= 2]
        return out
    except (json.JSONDecodeError, TypeError, OSError):
        return {}


def _save_completed_ranges(data: dict[str, list[tuple[str, str]]]) -> None:
    path = _completed_ranges_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {sym: list(ranges) for sym, ranges in data.items()}
    path.write_text(json.dumps({"ranges": serializable}, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_range_covered(date_from: str, date_to: str, ranges: list[tuple[str, str]]) -> bool:
    """True, если [date_from, date_to] целиком входит в один из сохранённых диапазонов."""
    for s, e in ranges:
        if s <= date_from and e >= date_to:
            return True
    return False


def _add_completed_range(
    data: dict[str, list[tuple[str, str]]],
    symbol: str,
    date_from: str,
    date_to: str,
) -> None:
    """Добавляет диапазон для symbol и сливает пересекающиеся/смежные интервалы."""
    ranges = list(data.get(symbol, []))
    ranges.append((date_from, date_to))
    ranges.sort(key=lambda x: x[0])
    merged: list[tuple[str, str]] = []
    for a, b in ranges:
        if merged and merged[-1][1] >= a:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    data[symbol] = merged


def _check_and_skip_if_done(symbol: str, date_from: str, date_to: str, force: bool) -> bool:
    """Если диапазон уже пройден и не --force: печатает сообщение и возвращает True (пропустить)."""
    if force:
        return False
    data = _load_completed_ranges()
    ranges = data.get(symbol, [])
    if _is_range_covered(date_from, date_to, ranges):
        logger.info("Диапазон уже был пройден: %s — %s. Пропуск (используй --force для повторного запуска).", date_from, date_to)
        print(f"Диапазон {date_from} — {date_to} уже был пройден для {symbol}. Пропуск.")
        print("Для повторного запуска укажи --force")
        return True
    return False


def _mark_range_done(symbol: str, date_from: str, date_to: str) -> None:
    """Сохраняет пройденный диапазон в журнал."""
    data = _load_completed_ranges()
    _add_completed_range(data, symbol, date_from, date_to)
    _save_completed_ranges(data)
    logger.info("Диапазон %s — %s записан в %s", date_from, date_to, _completed_ranges_path())


def _fake_orderbook_from_delta(mid: float, delta_ratio: float) -> dict[str, Any]:
    """Строит минимальный снимок стакана для analyze_dom: imbalance из delta_ratio."""
    import math
    r = max(-1.0, min(1.0, float(delta_ratio)))
    imb = 0.5 + 0.5 * r
    bid_vol = max(0.01, 2.0 * imb)
    ask_vol = max(0.01, 2.0 * (1.0 - imb))
    tick = 0.1
    return {
        "bids": [[mid - tick, bid_vol]],
        "asks": [[mid + tick, ask_vol]],
    }


def _sandbox_from_config(run_id: str | None = None) -> MicrostructureSandbox:
    """Создаёт MicrostructureSandbox с параметрами из конфига (как в main.py). run_id — для записи сделок в БД."""
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
    trail_trigger_pct = float(getattr(config, "SANDBOX_TRAIL_TRIGGER_PCT", 0) or 0)
    trail_pct = float(getattr(config, "SANDBOX_TRAIL_PCT", 0) or 0)
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

    return MicrostructureSandbox(
        run_id=run_id,
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


def run_backtest(
    symbol: str,
    date_from: str,
    date_to: str,
    *,
    tick_sec: int = DEFAULT_TICK_SEC,
    window_sec: float = DEFAULT_WINDOW_SEC,
    short_window_sec: float = 0.0,
) -> dict[str, Any]:
    """
    Реплей тиков за период: буфер сделок, каждые tick_sec секунд — окно window_sec,
    синтетический стакан из дельты, orderflow → sandbox.update(). Возвращает сводку.
    При создании песочницы старые логи (trades/skips) автоматически архивируются.
    Сделки пишутся в БД с run_id для отчётов по прогону.
    Перед запуском из БД удаляются незавершённые бэктест-прогоны (бракованные/прерванные).
    """
    conn_clean = get_connection()
    try:
        cur = conn_clean.cursor()
        n = delete_incomplete_sandbox_runs(cur, source="backtest")
        conn_clean.commit()
        if n > 0:
            logger.info("Удалено незавершённых бэктест-прогонов в БД: %s", n)
    finally:
        conn_clean.close()

    initial_usd = float(getattr(config, "SANDBOX_INITIAL_BALANCE", 100) or 100)
    run_id = f"backtest_{symbol}_{date_from}_{date_to}_{int(time.time())}"
    conn_run = get_connection()
    try:
        cur = conn_run.cursor()
        insert_sandbox_run(
            cur, run_id, symbol, "backtest", initial_usd,
            date_from=date_from, date_to=date_to,
        )
        conn_run.commit()
    finally:
        conn_run.close()

    sandbox = _sandbox_from_config(run_id=run_id)
    trend_filter_enabled = bool(getattr(config, "SANDBOX_TREND_FILTER", False))
    use_context_now_primary = bool(getattr(config, "SANDBOX_USE_CONTEXT_NOW_PRIMARY", False))
    use_context_now_only = bool(getattr(config, "SANDBOX_CONTEXT_NOW_ONLY", False))
    conn = get_connection() if trend_filter_enabled else None
    trend_tf = "15"
    trend_cache: dict[int, str] = {}  # bucket_15m -> "up"|"down"|"flat"

    window_ms = int(window_sec * 1000)
    tick_ms = tick_sec * 1000

    buffer: list[dict[str, Any]] = []
    next_tick_ms: int | None = None
    mid_prev = 0.0
    ticks_done = 0
    last_ts_ms = 0

    for trade in iter_trades(symbol, date_from=date_from, date_to=date_to):
        t_ms = trade.get("T") or 0
        if t_ms <= 0:
            continue
        buffer.append(trade)
        while buffer and (buffer[0].get("T") or 0) < t_ms - window_ms:
            buffer.pop(0)

        if next_tick_ms is None:
            next_tick_ms = (t_ms // tick_ms) * tick_ms + tick_ms

        while buffer and next_tick_ms <= t_ms:
            window = [x for x in buffer if (next_tick_ms - window_ms) <= (x.get("T") or 0) <= next_tick_ms]
            if window:
                delta = compute_volume_delta(
                    window,
                    window_sec=window_sec,
                    now_ts_ms=next_tick_ms,
                )
                delta_ratio = float(delta.get("delta_ratio") or 0.0)
                mid = window[-1].get("price") or mid_prev or 0.0
                if mid <= 0:
                    mid = mid_prev
                mid_prev = mid
                if mid > 0:
                    fake_snapshot = _fake_orderbook_from_delta(mid, delta_ratio)
                    of_result = analyze_orderflow(
                        orderbook_snapshot=fake_snapshot,
                        recent_trades=window,
                        candles=[],
                        window_sec=window_sec,
                        short_window_sec=short_window_sec,
                        now_ts_ms=next_tick_ms,
                        last_trades_k=10,
                    )
                    ts_sec = next_tick_ms // 1000
                    higher_tf_trend: str | None = None
                    if trend_filter_enabled and conn:
                        bucket_15m = (ts_sec // 900) * 900
                        if bucket_15m not in trend_cache:
                            cur = conn.cursor()
                            candles = get_candles_before(cur, symbol, trend_tf, ts_sec, limit=200)
                            tr = detect_trend(candles) if candles else {}
                            trend_cache[bucket_15m] = tr.get("direction", "flat")
                        higher_tf_trend = trend_cache[bucket_15m]
                    # Синтетический context_now для бэктеста: разрешаем long при положительной дельте, short при отрицательной
                    context_now: dict[str, Any] | None = None
                    if use_context_now_primary or use_context_now_only:
                        context_now = {
                            "allowed_long": delta_ratio > 0.15,
                            "allowed_short": delta_ratio < -0.15,
                            "short_window_delta_ratio": delta_ratio,
                        }
                    sandbox.update(of_result, mid, ts_sec, higher_tf_trend=higher_tf_trend, context_now=context_now)
                    ticks_done += 1
            next_tick_ms += tick_ms
        last_ts_ms = t_ms

    if conn:
        conn.close()

    if mid_prev <= 0 and buffer:
        mid_prev = buffer[-1].get("price") or 0.0
    equity = sandbox.equity(mid_prev) if mid_prev > 0 else sandbox.initial_balance
    summary = sandbox.get_summary(mid_prev) if mid_prev > 0 else {}

    conn_run = get_connection()
    try:
        cur = conn_run.cursor()
        update_sandbox_run_finished(
            cur, run_id,
            final_equity=equity,
            total_pnl=sandbox.total_realized_pnl,
            total_commission=sandbox.total_commission,
            trades_count=len(sandbox.trades),
        )
        conn_run.commit()
    finally:
        conn_run.close()

    return {
        "run_id": run_id,
        "symbol": symbol,
        "date_from": date_from,
        "date_to": date_to,
        "ticks_done": ticks_done,
        "initial_balance": sandbox.initial_balance,
        "total_realized_pnl": sandbox.total_realized_pnl,
        "total_commission": sandbox.total_commission,
        "equity": equity,
        "trades_count": len(sandbox.trades),
        "summary": summary,
        "state": sandbox.get_state(),
    }


def main() -> None:
    import argparse
    from datetime import date, timedelta

    from ..core.logging_config import setup_logging
    setup_logging()

    parser = argparse.ArgumentParser(description="Бэктест песочницы микроструктуры по историческим тикам")
    parser.add_argument("--symbol", "-s", default="", help="Символ (по умолчанию из конфига)")
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", default="", help="Начало периода (обязательно с --to или укажи --last-months)")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", default="", help="Конец периода (обязательно с --from или укажи --last-months)")
    parser.add_argument("--last-months", type=int, metavar="N", default=None, help="Бэктест за последние N месяцев (вместо --from/--to)")
    parser.add_argument("--tick-sec", type=int, default=DEFAULT_TICK_SEC, help="Интервал тика в секундах (по умолчанию %s)" % DEFAULT_TICK_SEC)
    parser.add_argument("--window-sec", type=float, default=DEFAULT_WINDOW_SEC, help="Окно Order Flow в секундах (по умолчанию %s)" % DEFAULT_WINDOW_SEC)
    parser.add_argument("--short-window-sec", type=float, default=0, help="Короткое окно для context (0 = выкл)")
    parser.add_argument("--force", action="store_true", help="Запустить даже если диапазон уже был пройден")
    parser.add_argument("--mark-done", action="store_true", help="Только записать диапазон как пройденный (без запуска бэктеста)")
    args = parser.parse_args()

    symbol = (args.symbol or getattr(config, "SYMBOL", "BTCUSDT") or "BTCUSDT").strip().upper()

    if args.last_months is not None:
        if args.last_months < 1:
            print("Ошибка: --last-months должен быть >= 1")
            sys.exit(1)
        end_date = date.today()
        start_date = end_date - timedelta(days=args.last_months * 31)
        date_from = start_date.isoformat()
        date_to = end_date.isoformat()
        logger.info("Период по --last-months %s: %s — %s", args.last_months, date_from, date_to)
    elif args.date_from and args.date_to:
        date_from = args.date_from.strip()
        date_to = args.date_to.strip()
    else:
        print("Укажи период: --from YYYY-MM-DD --to YYYY-MM-DD или --last-months N")
        sys.exit(1)

    if args.mark_done:
        _mark_range_done(symbol, date_from, date_to)
        print(f"Диапазон {date_from} — {date_to} для {symbol} отмечен как пройденный.")
        sys.exit(0)

    if _check_and_skip_if_done(symbol, date_from, date_to, args.force):
        sys.exit(0)

    logger.info("Бэктест песочницы: %s с %s по %s, тик=%ss, окно=%ss", symbol, date_from, date_to, args.tick_sec, args.window_sec)
    result = run_backtest(
        symbol,
        date_from,
        date_to,
        tick_sec=args.tick_sec,
        window_sec=args.window_sec,
        short_window_sec=args.short_window_sec or 0,
    )
    logger.info(
        "Итог: тиков=%s | старт=$%.0f | реализовано=$%.2f | комиссия=$%.2f | эквити=$%.2f | сделок=%s",
        result["ticks_done"],
        result["initial_balance"],
        result["total_realized_pnl"],
        result["total_commission"],
        result["equity"],
        result["trades_count"],
    )
    print()
    print("Бэктест песочницы микроструктуры")
    print("-" * 50)
    print(f"Символ: {result['symbol']}  Период: {result['date_from']} — {result['date_to']}")
    print(f"Тиков обработано: {result['ticks_done']}")
    print(f"Стартовый баланс: ${result['initial_balance']:.0f}")
    print(f"Реализованный PnL: ${result['total_realized_pnl']:.2f}")
    print(f"Комиссия: ${result['total_commission']:.2f}")
    print(f"Эквити на конец: ${result['equity']:.2f}")
    print(f"Сделок (открытий+закрытий): {result['trades_count']}")
    s = result.get("summary") or {}
    print(f"  Входов: {s.get('opens_count', 0)}  Выходов: {s.get('closes_count', 0)}  В плюс: {s.get('winning_trades', 0)}  В минус: {s.get('losing_trades', 0)}")
    _mark_range_done(symbol, date_from, date_to)
    print()
    sys.exit(0)


if __name__ == "__main__":
    main()
