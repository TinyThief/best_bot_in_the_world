"""
Определение тренда по всей БД на таймфрейме D с визуализацией.

Загружает все дневные свечи из БД для SYMBOL, считает тренд (detect_trend) на полной истории,
строит свечной график с зонами Вверх/Вниз/Флэт. На графике — последние max_candles_display свечей
(тренд при этом посчитан по всей выборке).

Запуск: python bin/trend_daily_full.py [--symbol BTCUSDT] [--lookback 100] [--max-display 2000] [--output путь.png]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core import config
from ..core.database import get_connection, get_candles
from ..utils.backtest_chart import build_daily_trend_full_chart


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Тренд по всей БД ТФ D с визуализацией (свечи + зоны Вверх/Вниз/Флэт)"
    )
    parser.add_argument("--symbol", type=str, default="", help="Пара (по умолчанию из .env)")
    parser.add_argument("--lookback", type=int, default=100, help="Окно для detect_trend")
    parser.add_argument("--max-display", type=int, default=2000, help="Сколько последних свечей рисовать")
    parser.add_argument(
        "--output", "-o", type=str, default="",
        help="Путь к PNG (по умолчанию: data/trend_daily_D_<symbol>.png)",
    )
    args = parser.parse_args()

    symbol = (args.symbol or config.SYMBOL or "BTCUSDT").strip().upper()
    if not symbol:
        print("Укажи --symbol или SYMBOL в .env", file=sys.stderr)
        sys.exit(1)

    root = Path(config.PROJECT_ROOT)
    out_path = args.output.strip()
    if not out_path:
        out_path = str(root / "data" / f"trend_daily_D_{symbol}.png")
    out_file = Path(out_path)
    if not out_file.is_absolute():
        out_file = root / out_file

    conn = get_connection()
    try:
        cur = conn.cursor()
        candles = get_candles(cur, symbol=symbol, timeframe="D", limit=None, order_asc=True)
    finally:
        conn.close()

    if not candles:
        print(f"В БД нет свечей ТФ D для {symbol}. Запусти bin/accumulate_db.py или bin/refill_tf_d.py.", file=sys.stderr)
        sys.exit(1)

    buf = build_daily_trend_full_chart(
        candles,
        symbol,
        lookback=args.lookback,
        max_candles_display=args.max_display,
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(buf.read())
    print(f"График сохранён: {out_file}")
    print(f"Свечей в БД (ТФ D): {len(candles)}, на графике: последние {min(len(candles), args.max_display)}")


if __name__ == "__main__":
    main()
