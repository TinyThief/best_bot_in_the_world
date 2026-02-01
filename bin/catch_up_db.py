"""
Одноразовая актуализация БД: обновление и догрузка недостающих участков по всем ТФ из TIMEFRAMES_DB.

Запуск из корня: python bin/catch_up_db.py

Использует модуль src/app/db_sync (open_and_prepare): бэкфилл пустых ТФ, run_once (подтягивает последние свечи),
run_catch_up (догружает пропуски с последней свечи до текущего времени по каждому ТФ),
run_extend_until_done (углубляет историю вглубь по всем ТФ, если AUTO_EXTEND_AT_STARTUP).
После выполнения БД актуальна на сегодня по всем ТФ. Для постоянного обновления — main.py или bin/accumulate_db.py.
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
    if not config.TIMEFRAMES_DB:
        print("TIMEFRAMES_DB пуст — задайте в .env и повторите.")
        return
    print("Актуализация БД по всем ТФ из TIMEFRAMES_DB: бэкфилл, догрузка пропусков, углубление истории...")
    conn = open_and_prepare()
    if conn is None:
        print("Не удалось подготовить БД.")
        return
    cur = conn.cursor()
    print("Последняя свеча по каждому ТФ:")
    for tf in config.TIMEFRAMES_DB:
        ms = get_latest_start_time(cur, config.SYMBOL, tf)
        if ms:
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            print(f"  ТФ {tf}: {dt.strftime('%Y-%m-%d %H:%M')} UTC")
        else:
            print(f"  ТФ {tf}: нет данных")
    close(conn)
    print("Готово: БД обновлена до текущей даты по всем ТФ. Для постоянного обновления — main.py или python bin/accumulate_db.py.")


if __name__ == "__main__":
    main()
