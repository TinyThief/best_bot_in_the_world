"""
Одноразовая догрузка БД до текущей даты.

Запуск: python catch_up_db.py

Делает run_once + run_catch_up по всем ТФ из TIMEFRAMES_DB:
догружает пропущенные свечи от последней в БД до «сейчас» и вставляет последние свечи с биржи.
После выполнения БД актуальна на сегодня. Для постоянного обновления запускайте main.py или accumulate_db.py.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.core import config
from src.core.database import get_latest_start_time
from src.core.logging_config import setup_logging
from src.app.db_sync import close, open_and_prepare


def main() -> None:
    setup_logging()
    conn = open_and_prepare()
    if conn is None:
        print("TIMEFRAMES_DB пуст — задайте в .env и повторите.")
        return
    cur = conn.cursor()
    # Показать дату последней свечи по ТФ D и 60 для проверки актуальности
    for tf in ("D", "60"):
        ms = get_latest_start_time(cur, config.SYMBOL, tf)
        if ms:
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            print(f"  Последняя свеча ТФ {tf}: {dt.strftime('%Y-%m-%d %H:%M')} UTC")
    close(conn)
    print("Готово: БД обновлена до текущей даты. Для постоянного обновления запускайте main.py или accumulate_db.py.")


if __name__ == "__main__":
    main()
