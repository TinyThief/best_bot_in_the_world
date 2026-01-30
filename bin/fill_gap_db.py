"""
Дозаполнение пропусков в БД между самой старой и самой новой свечой по каждому ТФ.
Запуск из корня: python bin/fill_gap_db.py

Полезно, если на графике /chart виден разрыв (например, часть года пропала).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core import config
from src.core.database import get_connection, init_db
from src.core.logging_config import setup_logging
from src.scripts.accumulate_db import run_fill_gap_for_timeframe


def main() -> None:
    setup_logging()
    if not config.TIMEFRAMES_DB:
        print("TIMEFRAMES_DB пуст — задайте в .env и повторите.")
        return
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    symbol = config.SYMBOL
    totals = {}
    for tf in config.TIMEFRAMES_DB:
        try:
            n = run_fill_gap_for_timeframe(cur, symbol, tf)
            totals[tf] = n
        except Exception as e:
            print(f"  ТФ {tf}: ошибка — {e}")
            totals[tf] = 0
    conn.commit()
    conn.close()
    if any(totals.values()):
        print("Дозаполнено пропусков:", totals)
    else:
        print("Пропусков не найдено (БД непрерывна по всем ТФ).")
    print("Готово.")


if __name__ == "__main__":
    main()
