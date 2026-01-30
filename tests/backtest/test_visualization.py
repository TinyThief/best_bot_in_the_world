"""
Проверка корректности визуализации бэктестов (фаз и тренда).
Запуск из корня: python -m tests.backtest.test_visualization
"""
from __future__ import annotations

import sys
from pathlib import Path

# Корень проекта в path
root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def main() -> None:
    from src.core import config
    from src.core.database import get_connection, get_candles
    from src.scripts.backtest_phases import run_for_chart
    from src.scripts.backtest_trend import run_for_chart as run_trend_for_chart
    from src.utils.backtest_chart import build_phases_chart, build_trend_chart, build_candlestick_trend_chart

    print("=== Проверка визуализации бэктестов ===\n")

    # Бэктест фаз (max_bars=None — весь период из БД)
    data_ph = run_for_chart(timeframe="60", max_bars=None, step=5)
    if data_ph:
        print("Phases run_for_chart: OK, bars_used =", data_ph.get("bars_used"))
        buf_ph = build_phases_chart(data_ph)
        print("Phases chart: построен, размер", len(buf_ph.getvalue()), "байт")
    else:
        print("Phases run_for_chart: None (в БД нет достаточного количества свечей по ТФ 60)")

    # Бэктест тренда (max_bars=None — весь период из БД)
    data_tr = run_trend_for_chart(timeframe="60", max_bars=None, step=5)
    if data_tr:
        print("Trend run_for_chart: OK, bars_used =", data_tr.get("bars_used"))
        buf_tr = build_trend_chart(data_tr)
        print("Trend chart: построен, размер", len(buf_tr.getvalue()), "байт")
    else:
        print("Trend run_for_chart: None (в БД нет достаточного количества свечей по ТФ 60)")

    # Свечной график с зонами TREND_UP (из БД)
    try:
        conn = get_connection()
        cur = conn.cursor()
        for tf in ("D", "60"):
            candles = get_candles(cur, config.SYMBOL, tf, limit=500, order_asc=False)
            if candles and len(candles) >= 101:
                buf_c = build_candlestick_trend_chart(candles, config.SYMBOL, tf, lookback=100)
                print(f"Candlestick chart (ТФ {tf}): построен, размер", len(buf_c.getvalue()), "байт")
                break
        else:
            print("Candlestick chart: в БД нет достаточного количества свечей по ТФ D или 60")
        conn.close()
    except Exception as e:
        print("Candlestick chart: ошибка —", e)

    print("\nГотово.")


if __name__ == "__main__":
    main()
