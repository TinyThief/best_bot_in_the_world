"""
Исторические данные для бэктеста: тики и (в будущем) стакан.

Выгрузка с https://www.bybit.com/derivatives/ru-RU/history-data → положить CSV в data/history/trades/{SYMBOL}/.
Загрузка для replay: load_trades(), iter_trades(), list_downloaded_trades().
"""
from __future__ import annotations

from .storage import (
    get_history_root,
    get_trades_dir,
    list_downloaded_trades,
    list_trade_files,
)
from .trades_loader import (
    load_trades,
    iter_trades,
    parse_trades_csv,
)

__all__ = [
    "get_history_root",
    "get_trades_dir",
    "list_trade_files",
    "list_downloaded_trades",
    "parse_trades_csv",
    "load_trades",
    "iter_trades",
]
