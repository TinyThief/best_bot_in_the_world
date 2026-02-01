"""
Песочница торговли по микроструктуре: виртуальная позиция и PnL по сигналу microstructure_signal.

Не исполняет реальные ордера. Стартовый баланс в USD (например $100); при открытии позиции размер
= баланс/цена (торгуем на полную сумму). PnL в USD. При выключении бота итог пишется в лог и в
logs/sandbox_result.txt. Запуск: ORDERFLOW_ENABLED=1 и MICROSTRUCTURE_SANDBOX_ENABLED=1.
"""
from __future__ import annotations

from typing import Any


def _mid_from_snapshot(snapshot: dict[str, Any]) -> float | None:
    """Цена mid из снимка стакана: (best_bid + best_ask) / 2."""
    bids = snapshot.get("bids") or []
    asks = snapshot.get("asks") or []
    if not bids or not asks:
        return None
    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        return (best_bid + best_ask) / 2.0
    except (IndexError, TypeError, ValueError):
        return None


class MicrostructureSandbox:
    """
    Виртуальная позиция и PnL в USD по сигналу микроструктуры (long/short/none).
    initial_balance — стартовый капитал в USD (например 100). При открытии позиции size = initial_balance / price
    (торгуем на полную сумму). position: 0 = flat, 1 = long, -1 = short.
    """

    def __init__(
        self,
        *,
        initial_balance: float = 100.0,
        min_confidence_to_open: float = 0.0,
    ):
        self.initial_balance = initial_balance
        self.min_confidence_to_open = min_confidence_to_open
        self.position: int = 0
        self.entry_price: float = 0.0
        self.size: float = 0.0  # в единицах актива, задаётся при открытии: initial_balance / price
        self.entry_ts: int = 0
        self.total_realized_pnl: float = 0.0
        self.last_signal: dict[str, Any] = {}
        self.last_ts: int = 0

    def get_state(self) -> dict[str, Any]:
        """Текущее состояние песочницы (позиция, PnL в USD, последний сигнал)."""
        return {
            "position": self.position,
            "position_side": "flat" if self.position == 0 else ("long" if self.position == 1 else "short"),
            "entry_price": self.entry_price,
            "entry_ts": self.entry_ts,
            "size": round(self.size, 6),
            "initial_balance_usd": self.initial_balance,
            "total_realized_pnl": round(self.total_realized_pnl, 4),
            "last_signal_direction": self.last_signal.get("direction", "—"),
            "last_signal_confidence": self.last_signal.get("confidence", 0.0),
            "last_ts": self.last_ts,
        }

    def unrealized_pnl(self, current_price: float) -> float:
        """Нереализованный PnL в USD по текущей цене."""
        if self.position == 0 or self.size <= 0:
            return 0.0
        if self.position == 1:
            return (current_price - self.entry_price) * self.size
        return (self.entry_price - current_price) * self.size

    def equity(self, current_price: float) -> float:
        """Текущий эквити в USD: начальный баланс + реализованный PnL + нереализованный PnL."""
        return self.initial_balance + self.total_realized_pnl + self.unrealized_pnl(current_price)

    def update(
        self,
        of_result: dict[str, Any],
        current_price: float,
        ts_sec: int,
    ) -> dict[str, Any]:
        """
        Обновляет песочницу: сигнал микроструктуры → открытие/закрытие виртуальной позиции.
        При открытии size = initial_balance / current_price (торгуем на полную сумму в USD).
        Возвращает состояние после обновления (PnL в USD).
        """
        from ..analysis.microstructure_signal import compute_microstructure_signal

        signal = compute_microstructure_signal(of_result)
        self.last_signal = signal
        self.last_ts = ts_sec
        direction = signal.get("direction", "none")
        confidence = float(signal.get("confidence") or 0.0)

        # Закрытие при смене направления или none
        if self.position != 0:
            if direction == "none" or (direction == "long" and self.position == -1) or (direction == "short" and self.position == 1):
                realized = self.unrealized_pnl(current_price)
                self.total_realized_pnl += realized
                self.position = 0
                self.entry_price = 0.0
                self.size = 0.0
                self.entry_ts = 0

        # Открытие при long/short: размер = initial_balance / price (в USD)
        if direction == "long" and confidence >= self.min_confidence_to_open:
            if self.position != 1:
                if self.position == -1:
                    realized = self.unrealized_pnl(current_price)
                    self.total_realized_pnl += realized
                self.position = 1
                self.entry_price = current_price
                self.size = self.initial_balance / current_price if current_price > 0 else 0.0
                self.entry_ts = ts_sec
        elif direction == "short" and confidence >= self.min_confidence_to_open:
            if self.position != -1:
                if self.position == 1:
                    realized = self.unrealized_pnl(current_price)
                    self.total_realized_pnl += realized
                self.position = -1
                self.entry_price = current_price
                self.size = self.initial_balance / current_price if current_price > 0 else 0.0
                self.entry_ts = ts_sec

        state = self.get_state()
        state["unrealized_pnl"] = round(self.unrealized_pnl(current_price), 4)
        state["current_price"] = current_price
        state["equity_usd"] = round(self.equity(current_price), 4)
        state["last_signal_reason"] = signal.get("reason", "")
        return state
