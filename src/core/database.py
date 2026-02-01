"""
База данных для обучающей выборки: свечи по парам и таймфреймам.
SQLite, одна таблица klines. Наращивание — вставка новых свечей без дубликатов.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)

TABLE_NAME = "klines"
# (symbol, timeframe, start_time) — уникальный ключ
ORDERFLOW_TABLE_NAME = "orderflow_metrics"
# Метрики микроструктуры (DOM, T&S, Delta, Sweeps) — одна запись на тик при ORDERFLOW_SAVE_TO_DB
ORDERFLOW_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {ORDERFLOW_TABLE_NAME} (
    symbol          TEXT NOT NULL,
    ts              INTEGER NOT NULL,
    imbalance_ratio REAL,
    bid_volume      REAL,
    ask_volume      REAL,
    delta           REAL,
    buy_volume      REAL,
    sell_volume     REAL,
    delta_ratio     REAL,
    volume_per_sec  REAL,
    trades_count    INTEGER,
    is_volume_spike INTEGER,
    last_sweep_side TEXT,
    last_sweep_time INTEGER,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS ix_orderflow_symbol_ts ON {ORDERFLOW_TABLE_NAME} (symbol, ts);
"""
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    symbol     TEXT NOT NULL,
    timeframe  TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    open       REAL NOT NULL,
    high       REAL NOT NULL,
    low        REAL NOT NULL,
    close      REAL NOT NULL,
    volume     REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, start_time)
);
CREATE INDEX IF NOT EXISTS ix_klines_symbol_tf_time ON {TABLE_NAME} (symbol, timeframe, start_time);
"""


def get_db_path() -> Path:
    """Путь к файлу БД из конфига или по умолчанию (относительные пути — от корня проекта)."""
    p = Path(config.DB_PATH).expanduser()
    if not p.is_absolute():
        p = config.PROJECT_ROOT / p
    return p.resolve()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Открывает соединение с БД, создаёт таблицу при первом запуске. WAL — быстрее чтение/запись при нескольких процессах."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.executescript(SCHEMA)
    con.executescript(ORDERFLOW_SCHEMA)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")  # 5 с ожидания при блокировке (несколько процессов)
    return con


def init_db(db_path: Path | None = None) -> None:
    """Создаёт файл БД и таблицу, если их ещё нет."""
    conn = get_connection(db_path)
    conn.close()
    logger.info("БД инициализирована: %s", get_db_path())


def insert_candles(
    cursor: sqlite3.Cursor,
    symbol: str,
    timeframe: str,
    candles: list[dict[str, Any]],
) -> int:
    """
    Вставляет свечи в klines. Дубликаты по (symbol, timeframe, start_time) игнорируются.
    Возвращает количество вставленных строк.
    """
    if not candles:
        return 0
    inserted = 0
    for c in candles:
        try:
            cursor.execute(
                f"""
                INSERT OR IGNORE INTO {TABLE_NAME}
                (symbol, timeframe, start_time, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    timeframe,
                    c["start_time"],
                    c["open"],
                    c["high"],
                    c["low"],
                    c["close"],
                    c["volume"],
                ),
            )
            inserted += cursor.rowcount
        except sqlite3.IntegrityError:
            pass
    return inserted


def get_latest_start_time(cursor: sqlite3.Cursor, symbol: str, timeframe: str) -> int | None:
    """Возвращает start_time последней (по времени) свечи в БД для данной пары и ТФ, или None."""
    cursor.execute(
        f"SELECT MAX(start_time) FROM {TABLE_NAME} WHERE symbol = ? AND timeframe = ?",
        (symbol, timeframe),
    )
    row = cursor.fetchone()
    return (int(row[0]) if row and row[0] is not None else None)


def get_oldest_start_time(cursor: sqlite3.Cursor, symbol: str, timeframe: str) -> int | None:
    """Возвращает start_time самой старой свечи для данной пары и ТФ, или None."""
    cursor.execute(
        f"SELECT MIN(start_time) FROM {TABLE_NAME} WHERE symbol = ? AND timeframe = ?",
        (symbol, timeframe),
    )
    row = cursor.fetchone()
    return (int(row[0]) if row and row[0] is not None else None)


def count_candles(cursor: sqlite3.Cursor, symbol: str | None = None, timeframe: str | None = None) -> int:
    """Количество свечей в БД, опционально с фильтром по symbol и/или timeframe."""
    conditions = []
    params = []
    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol)
    if timeframe:
        conditions.append("timeframe = ?")
        params.append(timeframe)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME} {where}", params)
    return int(cursor.fetchone()[0])


def delete_klines_for_symbol(cursor: sqlite3.Cursor, symbol: str) -> int:
    """Удаляет все свечи по символу. Возвращает количество удалённых строк."""
    cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE symbol = ?", (symbol,))
    return cursor.rowcount


def delete_klines_for_symbol_timeframe(
    cursor: sqlite3.Cursor, symbol: str, timeframe: str
) -> int:
    """Удаляет все свечи по символу и таймфрейму. Возвращает количество удалённых строк."""
    cursor.execute(
        f"DELETE FROM {TABLE_NAME} WHERE symbol = ? AND timeframe = ?",
        (symbol, timeframe),
    )
    return cursor.rowcount


def get_candles(
    cursor: sqlite3.Cursor,
    symbol: str,
    timeframe: str,
    *,
    limit: int | None = None,
    order_asc: bool = True,
) -> list[dict[str, Any]]:
    """
    Загружает свечи из БД по паре и таймфрейму, по порядку start_time.
    limit — максимум строк (для бэктеста можно взять последние N).
    order_asc=True — от старых к новым (как для бэктеста по времени).
    """
    order = "ASC" if order_asc else "DESC"
    sql = (
        f"SELECT start_time, open, high, low, close, volume "
        f"FROM {TABLE_NAME} WHERE symbol = ? AND timeframe = ? ORDER BY start_time {order}"
    )
    params: list[Any] = [symbol, timeframe]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    out = [
        {
            "start_time": int(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
        }
        for r in rows
    ]
    if not order_asc and out:
        out.reverse()
    return out


def insert_orderflow_metrics(
    cursor: sqlite3.Cursor,
    symbol: str,
    ts: int,
    of_result: dict[str, Any],
) -> int:
    """
    Вставляет одну запись метрик Order Flow (DOM, T&S, Delta, Sweeps).
    of_result — результат analyze_orderflow() (dom, time_and_sales, volume_delta, sweeps).
    ts — unix-время в секундах (момент записи).
    Возвращает 1 при успешной вставке, 0 при дубликате (INSERT OR REPLACE — всегда 1).
    """
    dom = of_result.get("dom") or {}
    tns = of_result.get("time_and_sales") or {}
    delta = of_result.get("volume_delta") or {}
    sweeps = of_result.get("sweeps") or {}
    try:
        cursor.execute(
            f"""
            INSERT OR REPLACE INTO {ORDERFLOW_TABLE_NAME}
            (symbol, ts, imbalance_ratio, bid_volume, ask_volume, delta, buy_volume, sell_volume,
             delta_ratio, volume_per_sec, trades_count, is_volume_spike, last_sweep_side, last_sweep_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                ts,
                dom.get("imbalance_ratio"),
                dom.get("raw_bid_volume"),
                dom.get("raw_ask_volume"),
                delta.get("delta"),
                delta.get("buy_volume"),
                delta.get("sell_volume"),
                delta.get("delta_ratio"),
                tns.get("volume_per_sec"),
                tns.get("trades_count") or delta.get("trades_count"),
                1 if tns.get("is_volume_spike") else 0,
                sweeps.get("last_sweep_side"),
                sweeps.get("last_sweep_time"),
            ),
        )
        return cursor.rowcount
    except sqlite3.IntegrityError:
        return 0


def get_orderflow_metrics(
    cursor: sqlite3.Cursor,
    symbol: str,
    *,
    limit: int | None = None,
    order_asc: bool = True,
    ts_from: int | None = None,
    ts_to: int | None = None,
) -> list[dict[str, Any]]:
    """
    Загружает метрики Order Flow по символу.
    order_asc=True — от старых к новым (для бэктеста по времени).
    ts_from / ts_to — опциональный диапазон (unix секунды).
    """
    conditions = ["symbol = ?"]
    params: list[Any] = [symbol]
    if ts_from is not None:
        conditions.append("ts >= ?")
        params.append(ts_from)
    if ts_to is not None:
        conditions.append("ts <= ?")
        params.append(ts_to)
    where = " AND ".join(conditions)
    order = "ASC" if order_asc else "DESC"
    sql = f"SELECT symbol, ts, imbalance_ratio, bid_volume, ask_volume, delta, buy_volume, sell_volume, delta_ratio, volume_per_sec, trades_count, is_volume_spike, last_sweep_side, last_sweep_time FROM {ORDERFLOW_TABLE_NAME} WHERE {where} ORDER BY ts {order}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    return [
        {
            "symbol": r[0],
            "ts": int(r[1]),
            "imbalance_ratio": r[2],
            "bid_volume": r[3],
            "ask_volume": r[4],
            "delta": r[5],
            "buy_volume": r[6],
            "sell_volume": r[7],
            "delta_ratio": r[8],
            "volume_per_sec": r[9],
            "trades_count": r[10],
            "is_volume_spike": bool(r[11]) if r[11] is not None else False,
            "last_sweep_side": r[12],
            "last_sweep_time": r[13],
        }
        for r in rows
    ]
