"""
База данных для обучающей выборки: свечи по парам и таймфреймам.
SQLite, одна таблица klines. Наращивание — вставка новых свечей без дубликатов.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

TABLE_NAME = "klines"
# (symbol, timeframe, start_time) — уникальный ключ
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
    """Путь к файлу БД из конфига или по умолчанию."""
    return Path(config.DB_PATH).expanduser().resolve()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Открывает соединение с БД, создаёт таблицу при первом запуске."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.executescript(SCHEMA)
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
