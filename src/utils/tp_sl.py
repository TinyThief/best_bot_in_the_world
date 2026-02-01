"""
Модуль TP/SL: фиксированные %, ATR-уровни, трейлинг-стоп, безубыток, композитные правила.

Используется в backtest_engine: handler возвращает (tp_price, sl_price) на каждом баре;
движок проверяет low <= sl → выход по SL, high >= tp → выход по TP.
Состояние (trailing_sl и т.д.) хранится в state и передаётся между барами.
"""
from __future__ import annotations

from typing import Any, Protocol

# Тип: (tp_price, sl_price) для лонга; оба в абсолютных ценах
TPSLLevels = tuple[float, float]


def atr_at_index(candles: list[dict[str, Any]], end_idx: int, period: int = 14) -> float | None:
    """ATR по свечам до end_idx включительно (true range = high - low)."""
    if end_idx < 0 or period <= 0 or end_idx + 1 < period:
        return None
    start = max(0, end_idx - period + 1)
    trs = [candles[i]["high"] - candles[i]["low"] for i in range(start, end_idx + 1)]
    if not trs:
        return None
    return sum(trs) / len(trs)


class TPSLHandler(Protocol):
    """Протокол обработчика TP/SL: возвращает уровни (tp_price, sl_price) для текущего бара."""

    def get_levels(
        self,
        entry_price: float,
        entry_bar_index: int,
        current_bar_index: int,
        candles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> TPSLLevels:
        ...


class FixedTPSL:
    """Фиксированные TP/SL в процентах от входа."""

    def __init__(self, tp_pct: float = 0.05, sl_pct: float = 0.02) -> None:
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct

    def get_levels(
        self,
        entry_price: float,
        entry_bar_index: int,
        current_bar_index: int,
        candles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> TPSLLevels:
        tp = entry_price * (1.0 + self.tp_pct)
        sl = entry_price * (1.0 - self.sl_pct)
        return (tp, sl)


class ATRBasedTPSL:
    """TP и SL в единицах ATR от входа (ATR считается на баре входа)."""

    def __init__(
        self,
        n_atr_tp: float = 2.0,
        n_atr_sl: float = 1.0,
        atr_period: int = 14,
    ) -> None:
        self.n_atr_tp = n_atr_tp
        self.n_atr_sl = n_atr_sl
        self.atr_period = atr_period

    def get_levels(
        self,
        entry_price: float,
        entry_bar_index: int,
        current_bar_index: int,
        candles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> TPSLLevels:
        if "_atr_entry" not in state:
            atr = atr_at_index(candles, entry_bar_index, self.atr_period)
            state["_atr_entry"] = atr if atr and atr > 0 else entry_price * 0.02
        atr = state["_atr_entry"]
        tp = entry_price + self.n_atr_tp * atr
        sl = entry_price - self.n_atr_sl * atr
        return (tp, sl)


class TrailingStopTPSL:
    """
    Трейлинг-стоп: начальный SL в %, после триггера прибыли — перенос в безубыток,
    затем трейлинг (SL = high * (1 - trail_pct)) для лонга.
    TP можно задать высоким (только выход по трейлингу) или в %.
    """

    def __init__(
        self,
        initial_sl_pct: float = 0.02,
        breakeven_trigger_pct: float = 0.01,
        trail_trigger_pct: float = 0.02,
        trail_pct: float = 0.015,
        tp_pct: float | None = 0.15,
    ) -> None:
        self.initial_sl_pct = initial_sl_pct
        self.breakeven_trigger_pct = breakeven_trigger_pct
        self.trail_trigger_pct = trail_trigger_pct
        self.trail_pct = trail_pct
        self.tp_pct = tp_pct if tp_pct is not None else 1.0

    def get_levels(
        self,
        entry_price: float,
        entry_bar_index: int,
        current_bar_index: int,
        candles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> TPSLLevels:
        if current_bar_index < entry_bar_index:
            return (entry_price * 2, entry_price * 0.5)
        bar = candles[current_bar_index]
        high = bar["high"]
        low = bar["low"]
        tp = entry_price * (1.0 + self.tp_pct)
        if "_sl_level" not in state:
            state["_sl_level"] = entry_price * (1.0 - self.initial_sl_pct)
        sl = state["_sl_level"]
        if high >= entry_price * (1.0 + self.breakeven_trigger_pct):
            sl = max(sl, entry_price)
        if high >= entry_price * (1.0 + self.trail_trigger_pct):
            trail_sl = high * (1.0 - self.trail_pct)
            sl = max(sl, trail_sl)
        state["_sl_level"] = sl
        return (tp, sl)


class ATRTrailingTPSL:
    """
    Композит: ATR-based начальные TP/SL; после движения в прибыль на 1*ATR — SL в безубыток,
    затем трейлинг от максимума (sl = high - trail_atr * ATR).
    """

    def __init__(
        self,
        n_atr_tp: float = 2.5,
        n_atr_sl: float = 1.0,
        trail_trigger_atr: float = 1.0,
        trail_atr: float = 0.5,
        atr_period: int = 14,
    ) -> None:
        self.n_atr_tp = n_atr_tp
        self.n_atr_sl = n_atr_sl
        self.trail_trigger_atr = trail_trigger_atr
        self.trail_atr = trail_atr
        self.atr_period = atr_period

    def get_levels(
        self,
        entry_price: float,
        entry_bar_index: int,
        current_bar_index: int,
        candles: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> TPSLLevels:
        if "_atr_entry" not in state:
            atr = atr_at_index(candles, entry_bar_index, self.atr_period)
            state["_atr_entry"] = atr if atr and atr > 0 else entry_price * 0.02
        atr = state["_atr_entry"]
        tp = entry_price + self.n_atr_tp * atr
        if "_sl_level" not in state:
            state["_sl_level"] = entry_price - self.n_atr_sl * atr
        sl = state["_sl_level"]
        bar = candles[current_bar_index] if current_bar_index < len(candles) else {}
        high = bar.get("high", entry_price)
        if high >= entry_price + self.trail_trigger_atr * atr:
            sl = max(sl, entry_price)
            trail_sl = high - self.trail_atr * atr
            sl = max(sl, trail_sl)
        state["_sl_level"] = sl
        return (tp, sl)


def make_fixed_handler(tp_pct: float = 0.05, sl_pct: float = 0.02) -> FixedTPSL:
    """Фабрика: фиксированные TP/SL (по умолчанию 5% / 2%)."""
    return FixedTPSL(tp_pct=tp_pct, sl_pct=sl_pct)


def make_atr_handler(
    n_atr_tp: float = 2.0,
    n_atr_sl: float = 1.0,
    atr_period: int = 14,
) -> ATRBasedTPSL:
    """Фабрика: TP/SL в ATR от входа."""
    return ATRBasedTPSL(n_atr_tp=n_atr_tp, n_atr_sl=n_atr_sl, atr_period=atr_period)


def make_trailing_handler(
    initial_sl_pct: float = 0.02,
    breakeven_trigger_pct: float = 0.01,
    trail_trigger_pct: float = 0.02,
    trail_pct: float = 0.015,
    tp_pct: float | None = 0.15,
) -> TrailingStopTPSL:
    """Фабрика: трейлинг-стоп с безубытком."""
    return TrailingStopTPSL(
        initial_sl_pct=initial_sl_pct,
        breakeven_trigger_pct=breakeven_trigger_pct,
        trail_trigger_pct=trail_trigger_pct,
        trail_pct=trail_pct,
        tp_pct=tp_pct,
    )


def make_atr_trailing_handler(
    n_atr_tp: float = 2.5,
    n_atr_sl: float = 1.0,
    trail_trigger_atr: float = 1.0,
    trail_atr: float = 0.5,
    atr_period: int = 14,
) -> ATRTrailingTPSL:
    """Фабрика: ATR TP/SL + трейлинг после 1*ATR прибыли."""
    return ATRTrailingTPSL(
        n_atr_tp=n_atr_tp,
        n_atr_sl=n_atr_sl,
        trail_trigger_atr=trail_trigger_atr,
        trail_atr=trail_atr,
        atr_period=atr_period,
    )
