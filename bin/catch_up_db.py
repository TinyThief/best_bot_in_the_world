"""
Одноразовая догрузка БД до текущей даты.
Запуск из корня проекта: python bin/catch_up_db.py

Делает run_once + run_catch_up по всем ТФ из TIMEFRAMES_DB.
После выполнения БД актуальна на сегодня. Для постоянного обновления — main.py или bin/accumulate_db.py.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

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
    for tf in ("D", "60"):
        ms = get_latest_start_time(cur, config.SYMBOL, tf)
        if ms:
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            print(f"  Последняя свеча ТФ {tf}: {dt.strftime('%Y-%m-%d %H:%M')} UTC")
    close(conn)
    print("Готово: БД обновлена до текущей даты. Для постоянного обновления — main.py или python bin/accumulate_db.py.")


if __name__ == "__main__":
    main()
