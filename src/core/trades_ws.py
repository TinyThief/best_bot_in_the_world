"""
WebSocket-поток исполненных сделок (Time & Sales) Bybit.

Подписка на publicTrade.{symbol}: в callback приходят пачки сделок (T, S, v, p, seq, L).
Накопление в кольцевом буфере; потокобезопасный get_recent_trades() и get_recent_trades_since(ts_ms).

Использование:
  from src.core.trades_ws import TradesStream
  stream = TradesStream(symbol="BTCUSDT")
  stream.start()
  trades = stream.get_recent_trades()  # последние N сделок
  trades_1m = stream.get_recent_trades_since(ts_ms)  # за окно (для T&S и Delta)
  stream.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from . import config

logger = logging.getLogger(__name__)

# Дефолтный размер буфера: последние 50k сделок (хватает на несколько минут при активном рынке)
TRADES_BUFFER_DEFAULT = 50_000


def _parse_trade(raw: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    """Нормализует одну сделку из ответа Bybit: T, s, S, v, p, i, seq, L → T, symbol, side, size, price, id, seq, direction."""
    try:
        t_ms = int(raw.get("T", 0))
        side = str(raw.get("S", "")).strip()  # Buy | Sell
        size = float(raw.get("v", 0))
        price = float(raw.get("p", 0))
        trade_id = raw.get("i", "")
        seq = int(raw.get("seq", 0))
        direction = raw.get("L", "")  # price direction для Perps
        if not side or size <= 0 or price <= 0:
            return None
        return {
            "T": t_ms,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "id": trade_id,
            "seq": seq,
            "direction": direction,
        }
    except (TypeError, ValueError):
        return None


class TradesStream:
    """
    Поток исполненных сделок по WebSocket: подписка на publicTrade.{symbol},
    кольцевой буфер последних N сделок, потокобезопасный get_recent_trades() и get_recent_trades_since(ts_ms).
    """

    def __init__(
        self,
        symbol: str | None = None,
        category: str | None = None,
        testnet: bool | None = None,
        max_trades: int = 0,
    ):
        self.symbol = (symbol or config.SYMBOL).strip().upper()
        self.category = (category or config.BYBIT_CATEGORY).strip().lower()
        self.testnet = testnet if testnet is not None else config.BYBIT_TESTNET
        self.max_trades = max_trades or TRADES_BUFFER_DEFAULT

        self._buffer: deque[dict[str, Any]] = deque(maxlen=self.max_trades)
        self._lock = threading.RLock()
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _on_message(self, message: dict[str, Any]) -> None:
        """Добавляет сделки из сообщения в буфер. data — массив сделок (до 1024 за раз)."""
        try:
            data = message.get("data")
            if not isinstance(data, list):
                return
            for raw in data:
                trade = _parse_trade(raw, self.symbol)
                if trade is None:
                    continue
                with self._lock:
                    self._buffer.append(trade)
        except Exception as e:
            logger.debug("TradesWS message parse: %s", e)

    def _run_ws(self) -> None:
        """Цикл в фоновом потоке: создание WS, подписка на trade_stream, ожидание до stop()."""
        try:
            from pybit.unified_trading import WebSocket
        except ImportError as e:
            logger.error("TradesWS: pybit не установлен или нет WebSocket: %s", e)
            return
        try:
            ping_interval = getattr(config, "ORDERFLOW_WS_PING_INTERVAL", 30)
            ping_timeout = getattr(config, "ORDERFLOW_WS_PING_TIMEOUT", 20)
            self._ws = WebSocket(
                testnet=self.testnet,
                channel_type=self.category,
                ping_interval=ping_interval,
                ping_timeout=ping_timeout,
            )
            self._ws.trade_stream(
                symbol=self.symbol,
                callback=self._on_message,
            )
            while not self._stop.wait(timeout=0.5):
                pass
        except Exception as e:
            logger.exception("TradesWS поток: %s", e)
        finally:
            try:
                if self._ws is not None and hasattr(self._ws, "exit"):
                    self._ws.exit()
            except Exception:
                pass
            self._ws = None

    def start(self) -> None:
        """Запускает фоновый поток с WebSocket и подпиской на сделки."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()
        logger.info("TradesWS запущен: %s, буфер %s", self.symbol, self.max_trades)

    def stop(self) -> None:
        """Останавливает поток и закрывает WebSocket."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._ws = None
        logger.info("TradesWS остановлен: %s", self.symbol)

    def get_recent_trades(self, n: int | None = None) -> list[dict[str, Any]]:
        """
        Копия последних n сделок из буфера (потокобезопасно).
        n=None — все сделки в буфере (до max_trades).
        Каждая сделка: T (мс), symbol, side (Buy/Sell), size, price, id, seq, direction.
        """
        with self._lock:
            buf = list(self._buffer)
        if n is None or n <= 0:
            return buf
        return buf[-n:]

    def get_recent_trades_since(self, ts_ms: int) -> list[dict[str, Any]]:
        """
        Сделки с временем T >= ts_ms (для окна по времени, например последние 60 сек).
        ts_ms = int((time.time() - window_sec) * 1000).
        """
        with self._lock:
            buf = list(self._buffer)
        return [t for t in buf if t.get("T", 0) >= ts_ms]
