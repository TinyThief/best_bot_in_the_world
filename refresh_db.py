"""Полное обновление БД: удаление файла и загрузка всех таймфреймов с биржи.

Запуск (из корня проекта):
  python refresh_db.py [--yes]
  py -3 refresh_db.py [--yes]

  --yes  без подтверждения (удобно для скриптов)

Перед запуском останови бота и другие процессы, использующие БД (main.py, telegram_bot.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.core import config
from src.core.database import get_db_path, get_connection
from src.core.logging_config import setup_logging
from src.scripts.full_backfill import full_backfill_one_tf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Удалить БД и заново загрузить все таймфреймы с Bybit"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Выполнить без запроса подтверждения",
    )
    args = parser.parse_args()

    setup_logging()

    if not config.TIMEFRAMES_DB:
        print("Ошибка: задайте TIMEFRAMES_DB в .env. Пример: 1,3,5,15,30,60,120,240,D,W,M")
        sys.exit(1)

    db_path = get_db_path()
    symbol = config.SYMBOL
    category = config.BYBIT_CATEGORY

    if not args.yes:
        print(f"Будет удалён файл БД: {db_path}")
        print(f"Пара: {symbol}, таймфреймы: {config.TIMEFRAMES_DB}")
        print("Убедись, что бот и другие процессы, использующие БД, остановлены.")
        try:
            answer = input("Продолжить? [y/N]: ").strip().lower()
        except EOFError:
            answer = "n"
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено.")
            sys.exit(0)

    if db_path.exists():
        try:
            db_path.unlink()
            print(f"Файл удалён: {db_path}")
        except OSError as e:
            print(f"Не удалось удалить файл (возможно, БД открыта другим процессом): {e}")
            print("Останови бота и повтори, либо используй: python full_backfill.py --clear")
            sys.exit(1)
    else:
        print(f"Файл не найден (будет создан): {db_path}")

    conn = get_connection()
    cursor = conn.cursor()

    for tf in config.TIMEFRAMES_DB:
        try:
            full_backfill_one_tf(cursor, symbol, tf, category)
            conn.commit()
        except Exception as e:
            print(f"Ошибка по ТФ {tf}: {e}")
            conn.rollback()

    conn.close()
    print("Готово. БД актуализирована по всем таймфреймам.")


if __name__ == "__main__":
    main()
