"""
Дозаполнение пропусков в БД между самой старой и самой новой свечой по каждому ТФ.

Запуск: python fill_gap_db.py

Полезно, если на графике /chart виден разрыв (например, часть 2025 года пропала):
в БД есть старые и новые свечи, но нет данных за какой-то период. Скрипт запрашивает
у биржи недостающий диапазон и вставляет только отсутствующие свечи (дубликаты не трогает).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
