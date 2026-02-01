"""
WebSocket-стакан Bybit в реальном времени.

Подписка на orderbook.{depth}.{symbol}: первый ответ — snapshot, далее — delta.
Локальный стакан обновляется по правилам Bybit: size=0 → удалить уровень, иначе вставить/обновить.
Потокобезопасный доступ к текущему снимку через get_snapshot().

Использование:
  from src.core.orderbook_ws import OrderbookStream
  stream = OrderbookStream(symbol="BTCUSDT", depth=50)
  stream.start()
  ob = stream.get_snapshot()  # {"bids": [[price, size], ...], "asks": ..., "ts", "u", "seq"}
  stream.stop()
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from . import config

logger = logging.getLogger(__name__)

# Допустимые глубины для linear: 1 (10ms), 50 (20ms), 200 (100ms), 1000 (200ms)
ORDERBOOK_WS_DEPTHS_LINEAR = (1, 50, 200, 1000)


def _apply_levels(current: dict[str, float], updates: list[list[Any]]) -> None:
    """Обновляет словарь цена -> размер: size=0 удаляет, иначе вставляет/обновляет."""
    for item in updates:
        try:
            price_str = str(item[0]).strip()
            size = float(item[1])
            if size == 0:
                current.pop(price_str, None)
            else:
                current[price_str] = size
        except (IndexError, TypeError, ValueError):
            continue


def _to_sorted_list(levels: dict[str, float], descending: bool) -> list[list[float]]:
    """Преобразует словарь цена->размер в отсортированный список [[price, size], ...]."""
    out: list[list[float]] = []
    for price_str, size in levels.items():
        try:
            p = float(price_str)
            out.append([p, size])
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0], reverse=descending)
    return out


class OrderbookStream:
    """
    Поток стакана по WebSocket: подписка на orderbook.{depth}.{symbol},
    поддержка snapshot и delta, потокобезопасный get_snapshot().
    """

    def __init__(
        self,
        symbol: str | None = None,
        depth: int | None = None,
        category: str | None = None,
        testnet: bool | None = None,
    ):
        self.symbol = (symbol or config.SYMBOL).strip().upper()
        self.depth = depth if depth is not None else min(50, getattr(config, "ORDERBOOK_LIMIT", 25))
        if self.depth not in ORDERBOOK_WS_DEPTHS_LINEAR:
            self.depth = 50  # ближайший поддерживаемый для linear
        self.category = (category or config.BYBIT_CATEGORY).strip().lower()
        self.testnet = testnet if testnet is not None else config.BYBIT_TESTNET

        self._bids: dict[str, float] = {}
        self._asks: dict[str, float] = {}
        self._ts: int = 0
        self._u: int = 0
        self._seq: int = 0
        self._lock = threading.RLock()
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _on_message(self, message: dict[str, Any]) -> None:
        """
        Обработка сообщения: snapshot — полная замена стакана, delta — применение изменений.
        pybit для orderbook передаёт в callback уже объединённое состояние (type=snapshot, data=полный стакан),
        но на случай сырых сообщений обрабатываем и snapshot, и delta (u==1 = перезапись по правилам Bybit).
        """
        try:
            data = message.get("data") or {}
            ts = int(message.get("ts", 0) or data.get("ts", 0))
            u = int(data.get("u", 0))
            seq = int(data.get("seq", 0))
            bids_raw = data.get("b") or []
            asks_raw = data.get("a") or []
            msg_type = message.get("type", "delta")

            with self._lock:
                if msg_type == "snapshot" or u == 1:
                    self._bids.clear()
                    self._asks.clear()
                    for item in bids_raw:
                        try:
                            price_str = str(item[0]).strip()
                            size = float(item[1])
                            if size > 0:
                                self._bids[price_str] = size
                        except (IndexError, TypeError, ValueError):
                            continue
                    for item in asks_raw:
                        try:
                            price_str = str(item[0]).strip()
                            size = float(item[1])
                            if size > 0:
                                self._asks[price_str] = size
                        except (IndexError, TypeError, ValueError):
                            continue
                else:
                    _apply_levels(self._bids, bids_raw)
                    _apply_levels(self._asks, asks_raw)
                self._ts = ts
                self._u = u
                self._seq = seq
        except Exception as e:
            logger.debug("OrderbookWS message parse: %s", e)

    def _run_ws(self) -> None:
        """Цикл в фоновом потоке: создание WS, подписка, ожидание до stop()."""
        try:
            from pybit.unified_trading import WebSocket
        except ImportError as e:
            logger.error("OrderbookWS: pybit не установлен или нет WebSocket: %s", e)
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
            self._ws.orderbook_stream(
                depth=self.depth,
                symbol=self.symbol,
                callback=self._on_message,
            )
            while not self._stop.wait(timeout=0.5):
                pass
        except Exception as e:
            logger.exception("OrderbookWS поток: %s", e)
        finally:
            try:
                if self._ws is not None and hasattr(self._ws, "exit"):
                    self._ws.exit()
            except Exception:
                pass
            self._ws = None

    def start(self) -> None:
        """Запускает фоновый поток с WebSocket и подпиской на стакан."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()
        logger.info("OrderbookWS запущен: %s depth=%s", self.symbol, self.depth)

    def stop(self) -> None:
        """Останавливает поток и закрывает WebSocket."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._ws = None
        logger.info("OrderbookWS остановлен: %s", self.symbol)

    def get_snapshot(self) -> dict[str, Any]:
        """
        Текущий снимок стакана (потокобезопасно).
        Формат как у exchange.get_orderbook: bids/asks — [[price, size], ...], ts, u, seq, symbol.
        """
        with self._lock:
            bids = _to_sorted_list(self._bids, descending=True)
            asks = _to_sorted_list(self._asks, descending=False)
            return {
                "symbol": self.symbol,
                "bids": bids,
                "asks": asks,
                "ts": self._ts,
                "u": self._u,
                "seq": self._seq,
            }
