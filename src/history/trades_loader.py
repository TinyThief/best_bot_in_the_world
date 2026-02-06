"""
Загрузка и парсинг исторических тиков из CSV (выгрузка Bybit history-data).

Формат на выходе совместим с TradesStream/analyze_orderflow: T (ms), symbol, side, size, price, id, seq, direction.
Поддерживаются CSV с заголовками: timestamp/exec_time, price, size/qty, side (Buy/Sell).
"""
from __future__ import annotations

import csv
import gzip
import logging
from pathlib import Path
from typing import Any, Iterator

from .storage import get_trades_dir, list_trade_files

logger = logging.getLogger(__name__)

def _normalize_ts(raw: Any) -> int:
    """Привести время к миллисекундам."""
    if raw is None or raw == "":
        return 0
    try:
        v = float(raw)
        if v < 1e12:
            return int(v * 1000)
        return int(v)
    except (TypeError, ValueError):
        return 0


def _parse_trade_row(
    row: dict[str, str],
    symbol: str,
    time_col: str,
    price_col: str,
    size_col: str,
    side_col: str,
    row_num: int,
) -> dict[str, Any] | None:
    """Преобразовать одну строку CSV в формат для orderflow."""
    try:
        t_ms = _normalize_ts(row.get(time_col))
        price = float(row.get(price_col, 0))
        size = float(row.get(size_col, 0))
        side = (row.get(side_col, "") or "").strip()
        if not side:
            side = "Buy" if row.get("side", "").upper().startswith("B") else "Sell"
        if size <= 0 or price <= 0:
            return None
        if side.upper() not in ("BUY", "SELL"):
            side = "Buy" if "buy" in side.lower() or side == "B" else "Sell"
        return {
            "T": t_ms,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "id": row.get("id", row.get("exec_id", "")) or f"row_{row_num}",
            "seq": int(row.get("seq", row_num)),
            "direction": row.get("direction", row.get("L", "")),
        }
    except (TypeError, ValueError, KeyError):
        return None


def _detect_columns(headers: list[str]) -> tuple[str, str, str, str] | None:
    """По заголовкам CSV определить имена колонок времени, цены, размера, стороны."""
    h_lower = [s.strip().lower() for s in headers]
    time_col = price_col = size_col = side_col = ""
    for i, h in enumerate(h_lower):
        if not h:
            continue
        name = headers[i]
        if h in ("timestamp", "exec_time", "time", "t", "ts", "datetime") or "time" in h:
            time_col = name
        elif h in ("price", "p", "exec_price", "trade_price") or "price" in h:
            price_col = name
        elif h in ("size", "qty", "v", "exec_qty", "amount", "quantity") or "qty" in h or "size" in h:
            size_col = name
        elif h in ("side", "s", "exec_side", "side_ind") or "side" in h:
            side_col = name
    if time_col and price_col and size_col:
        return (time_col, price_col, size_col, side_col or "side")
    return None


def parse_trades_csv(
    path: Path,
    symbol: str,
) -> list[dict[str, Any]]:
    """
    Прочитать CSV файл тиков и вернуть список сделок в формате для analyze_orderflow.
    path — путь к .csv или .csv.gz.
    """
    trades: list[dict[str, Any]] = []
    is_gz = path.suffix == ".gz" or path.name.endswith(".csv.gz")
    try:
        if is_gz:
            f = gzip.open(path, "rt", encoding="utf-8", newline="")
        else:
            f = open(path, "r", encoding="utf-8", newline="")
        with f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            cols = _detect_columns(list(headers))
            if not cols:
                # Без заголовков — пробуем порядок: timestamp, price, size, side
                if headers and len(headers) >= 4:
                    time_col, price_col, size_col, side_col = headers[0], headers[1], headers[2], headers[3]
                    cols = (time_col, price_col, size_col, side_col)
                else:
                    logger.warning("Не удалось определить колонки в %s: %s", path, headers)
                    return trades
            time_col, price_col, size_col, side_col = cols
            for row_num, row in enumerate(reader, 1):
                t = _parse_trade_row(row, symbol, time_col, price_col, size_col, side_col, row_num)
                if t and t["T"] > 0:
                    trades.append(t)
    except Exception as e:
        logger.exception("Ошибка чтения %s: %s", path, e)
    return trades


def load_trades(
    symbol: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """
    Загрузить все тики за период из локальных CSV в каталоге trades/{symbol}/.
    date_from / date_to — строки YYYY-MM-DD (включительно). Если None — все файлы.
    Возвращает список сделок, отсортированный по T (времени).
    """
    files = list_trade_files(symbol)
    all_trades: list[dict[str, Any]] = []
    for path, date_str in files:
        d = date_str[:10] if len(date_str) >= 10 else date_str
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        chunk = parse_trades_csv(path, symbol)
        all_trades.extend(chunk)
    all_trades.sort(key=lambda x: x["T"])
    return all_trades


def iter_trades(
    symbol: str,
    ts_start_ms: int | None = None,
    ts_end_ms: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Итератор по тикам за период (для replay без загрузки всего в память).
    Фильтр по времени: ts_start_ms <= T < ts_end_ms (если заданы).
    Альтернативно по датам: date_from, date_to (YYYY-MM-DD).
    """
    files = list_trade_files(symbol)
    for path, date_str in files:
        d = date_str[:10] if len(date_str) >= 10 else date_str
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        for t in parse_trades_csv(path, symbol):
            if ts_start_ms is not None and t["T"] < ts_start_ms:
                continue
            if ts_end_ms is not None and t["T"] >= ts_end_ms:
                continue
            yield t
