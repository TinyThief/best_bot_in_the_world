"""
Универсальный движок бэктеста с TP/SL.

Сигнальная функция: (window, bar_index, candles, timeframe) -> "long" | "exit_long" | "none".
На каждом баре в позиции: сначала проверка SL, затем TP (фиксированные % или через tp_sl_handler),
затем сигнал exit_long. Депозит 100$, только лонги.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

SignalFn = Callable[[list[dict[str, Any]], int, list[dict[str, Any]], str], str]


class TPSLHandlerLike(Protocol):
    def get_levels(
        self,
        entry_price: float,
        entry_bar_index: int,
        current_bar_index: int,
        candles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> tuple[float, float]:
        ...


def run_backtest(
    candles: list[dict[str, Any]],
    lookback: int,
    signal_fn: SignalFn,
    *,
    timeframe: str = "D",
    tp_pct: float | None = 0.04,
    sl_pct: float | None = 0.02,
    tp_sl_handler: TPSLHandlerLike | None = None,
    initial_deposit: float = 100.0,
    max_bars_in_position: int | None = None,
) -> dict[str, Any]:
    """
    Прогон бэктеста по свечам с заданной сигнальной функцией и TP/SL.

    signal_fn(window, bar_index, candles, timeframe) -> "long" | "exit_long" | "none".
    window = candles[bar_index - lookback : bar_index].

    TP/SL задаются либо (tp_pct, sl_pct), либо tp_sl_handler (модуль tp_sl: ATR, трейлинг и т.д.).
    Если задан tp_sl_handler, tp_pct/sl_pct игнорируются. Если оба не заданы (handler None и tp/sl None) — выход только по сигналу.
    max_bars_in_position — при достижении числа баров в позиции выход по time_stop (без учёта TP/SL).
    Возвращает: initial_deposit, final_equity, n_trades, trades, max_drawdown_pct,
    equity_curve, candles (тот же список).
    """
    if len(candles) < lookback + 1:
        return {
            "initial_deposit": initial_deposit,
            "final_equity": initial_deposit,
            "n_trades": 0,
            "trades": [],
            "max_drawdown_pct": 0.0,
            "equity_curve": [],
            "candles": candles,
            "error": f"Мало свечей: {len(candles)} < {lookback + 1}",
        }

    balance = initial_deposit
    position = 0  # 0 = в кэше, 1 = в лонге
    entry_price: float = 0.0
    entry_bar_index: int = 0
    shares: float = 0.0
    tp_sl_state: dict[str, Any] = {}
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    peak_equity = initial_deposit

    for i in range(lookback, len(candles)):
        window = candles[i - lookback : i]
        bar = candles[i]
        open_ = bar["open"]
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]
        ts_ms = bar["start_time"]

        signal = signal_fn(window, i, candles, timeframe)

        # В позиции: тайм-стоп, затем SL, TP (фиксированные % или handler), затем сигнал выхода
        if position == 1 and entry_price > 0:
            exit_reason: str | None = None
            exit_price_val = close
            if max_bars_in_position is not None and (i - entry_bar_index) >= max_bars_in_position:
                exit_reason = "time_stop"
            use_tp_sl = (
                exit_reason is None
                and (tp_sl_handler is not None or (tp_pct is not None and sl_pct is not None))
            )
            if use_tp_sl:
                if tp_sl_handler is not None:
                    tp_level, sl_level = tp_sl_handler.get_levels(
                        entry_price, entry_bar_index, i, candles, tp_sl_state
                    )
                else:
                    sl_level = entry_price * (1.0 - sl_pct)
                    tp_level = entry_price * (1.0 + tp_pct)
                if low <= sl_level:
                    exit_reason = "sl"
                    exit_price_val = sl_level
                elif high >= tp_level:
                    exit_reason = "tp"
                    exit_price_val = tp_level
            if exit_reason is None and signal == "exit_long":
                exit_reason = "signal"

            if exit_reason:
                balance = shares * exit_price_val if exit_price_val > 0 else 0.0
                pnl = balance - (shares * entry_price)
                trades.append({
                    "side": "sell",
                    "time": ts_ms,
                    "price": exit_price_val,
                    "shares": shares,
                    "entry_price": entry_price,
                    "pnl": pnl,
                    "pnl_pct": (pnl / (shares * entry_price) * 100) if entry_price > 0 else 0,
                    "exit_reason": exit_reason,
                })
                position = 0
                shares = 0.0
                entry_price = 0.0
                tp_sl_state = {}

        # Вход в лонг
        if position == 0 and signal == "long" and balance > 0 and close > 0:
            entry_price = close
            entry_bar_index = i
            shares = balance / close
            position = 1
            balance = 0.0
            tp_sl_state = {}
            trades.append({
                "side": "buy",
                "time": ts_ms,
                "price": entry_price,
                "shares": shares,
            })

        # Эквити на конец бара
        if position == 1:
            equity = shares * close
        else:
            equity = balance
        equity_curve.append(equity)
        if equity > peak_equity:
            peak_equity = equity

    final_equity = equity_curve[-1] if equity_curve else initial_deposit
    max_dd = 0.0
    peak = initial_deposit
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        "initial_deposit": initial_deposit,
        "final_equity": final_equity,
        "n_trades": len([t for t in trades if t["side"] == "sell"]),
        "trades": trades,
        "max_drawdown_pct": max_dd,
        "equity_curve": equity_curve,
        "candles": candles,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "tp_sl_handler": tp_sl_handler,
    }
