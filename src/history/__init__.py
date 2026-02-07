"""
Исторические данные для бэктеста: тики и (в будущем) стакан.

Выгрузка с https://www.bybit.com/derivatives/ru-RU/history-data → положить CSV в data/history/trades/{SYMBOL}/.
Подгрузка недостающих тиков: ensure_ticks(), refill_ticks_from_public(), refill_ticks_today_from_api().
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
from .trades_refill import (
    ensure_ticks,
    get_missing_dates,
    refill_ticks_from_public,
    refill_ticks_today_from_api,
    download_ticks_from_public,
)

__all__ = [
    "get_history_root",
    "get_trades_dir",
    "list_trade_files",
    "list_downloaded_trades",
    "parse_trades_csv",
    "load_trades",
    "iter_trades",
    "get_missing_dates",
    "download_ticks_from_public",
    "refill_ticks_from_public",
    "refill_ticks_today_from_api",
    "ensure_ticks",
]
