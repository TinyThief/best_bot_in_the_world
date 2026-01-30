"""
Отчёт по бэктесту тренда: запуск бэктеста на ТФ D (вся БД) и сохранение графика точности.
График: столбцы по направлениям (Вверх/Вниз/Флэт) — средняя доходность и количество наблюдений.
Запуск: python bin/trend_backtest_report.py [--tf D] [--output путь.png]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core import config
from .backtest_trend import run_for_chart
from ..utils.backtest_chart import build_trend_chart


def main() -> None:
    parser = argparse.ArgumentParser(description="Отчёт по бэктесту тренда: график точности по направлениям")
    parser.add_argument("--symbol", type=str, default="", help="Пара (по умолчанию из .env)")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default="D", help="Таймфрейм (по умолчанию D)")
    parser.add_argument("--all", dest="all_bars", action="store_true", help="Вся БД (иначе последние 2500 свечей)")
    parser.add_argument("--output", "-o", type=str, default="", help="Путь к PNG (по умолчанию data/trend_backtest_<TF>.png)")
    args = parser.parse_args()

    symbol = (args.symbol or config.SYMBOL or "BTCUSDT").strip().upper()
    root = Path(config.PROJECT_ROOT)
    out_path = args.output.strip()
    if not out_path:
        out_path = str(root / "data" / f"trend_backtest_{args.timeframe}.png")
    out_file = Path(out_path)
    if not out_file.is_absolute():
        out_file = root / out_file

    max_bars = None if args.all_bars else 2500
    data = run_for_chart(
        symbol=symbol,
        timeframe=args.timeframe,
        max_bars=max_bars,
        lookback=100,
        forward_bars=20,
        step=5,
    )

    if not data:
        print(
            f"Недостаточно данных в БД для бэктеста (пара={symbol}, ТФ={args.timeframe}). "
            "Запусти bin/accumulate_db.py или bin/refill_tf_d.py.",
            file=sys.stderr,
        )
        sys.exit(1)

    buf = build_trend_chart(data, dpi=120)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(buf.read())
    stats = data["stats"]
    acc = stats.get("total_accuracy", 0) * 100
    n = stats.get("total_n", 0)
    print(f"График сохранён: {out_file}")
    print(f"Точность (up+down): {acc:.1f}% (n={n})")


if __name__ == "__main__":
    main()
