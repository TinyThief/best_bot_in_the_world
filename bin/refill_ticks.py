"""Подгрузка недостающих тиков за период: public.bybit.com + при необходимости REST API за сегодня.

Запуск из корня:
  python bin/refill_ticks.py --from 2026-01-01 --to 2026-01-31 [--symbol BTCUSDT]
  python bin/refill_ticks.py --from 2026-01-01 --to 2026-01-31 --no-api-today   # только public, без API за сегодня
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core import config
from src.history.trades_refill import ensure_ticks, get_missing_dates


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Подгрузить тики, которых нет: с public.bybit.com и (опционально) REST API за сегодня"
    )
    parser.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", required=True, help="Начало диапазона")
    parser.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", required=True, help="Конец диапазона")
    parser.add_argument("--symbol", "-s", default="", help="Символ (по умолчанию из конфига)")
    parser.add_argument("--no-public", action="store_true", help="Не скачивать с public.bybit.com")
    parser.add_argument("--no-api-today", action="store_true", help="Не подгружать сегодняшний день по API")
    args = parser.parse_args()

    symbol = (args.symbol or getattr(config, "SYMBOL", "BTCUSDT") or "BTCUSDT").strip().upper()
    date_from = args.date_from.strip()
    date_to = args.date_to.strip()

    missing = get_missing_dates(symbol, date_from, date_to)
    if not missing:
        print(f"Все тики за {date_from}..{date_to} для {symbol} уже есть.")
        sys.exit(0)

    print(f"Не хватает тиков за {len(missing)} дн.: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    result = ensure_ticks(
        symbol,
        date_from,
        date_to,
        use_public=not args.no_public,
        use_api_today=not args.no_api_today,
    )
    if result.get("refill_public"):
        r = result["refill_public"]
        print(f"Public: загружено {r.get('downloaded', 0)}, не удалось {len(r.get('failed', []))}")
    if result.get("refill_api_today", 0):
        print(f"API за сегодня: записано {result['refill_api_today']} строк")
    print("Готово.")
    sys.exit(0)


if __name__ == "__main__":
    main()
