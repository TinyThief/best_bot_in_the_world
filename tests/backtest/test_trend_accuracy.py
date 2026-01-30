"""
Проверка точности бэктеста тренда на ТФ D (дымовой тест: accuracy >= 0.50).
Требует БД с дневными свечами. Запуск из корня: python -m tests.backtest.test_trend_accuracy
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def test_trend_backtest_accuracy_on_d() -> None:
    """Бэктест тренда на ТФ D: сводная точность (up+down) не ниже 0.50."""
    from src.core import config
    from src.core.database import get_connection, get_candles
    from src.scripts.backtest_trend import run_for_chart

    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, config.SYMBOL, "D", limit=2500, order_asc=False)
    conn.close()

    if not candles or len(candles) < 150:
        import unittest
        raise unittest.SkipTest("В БД недостаточно свечей ТФ D для бэктеста (нужно минимум 150)")  # noqa: B904

    data = run_for_chart(
        symbol=config.SYMBOL,
        timeframe="D",
        max_bars=len(candles),
        lookback=100,
        forward_bars=20,
        step=5,
    )
    assert data is not None
    stats = data["stats"]
    total_accuracy = stats["total_accuracy"]
    total_n = stats["total_n"]
    assert total_n > 0
    assert total_accuracy >= 0.50, (
        f"Ожидалась сводная точность тренда >= 0.50, получено {total_accuracy:.2%} (n={total_n})"
    )


if __name__ == "__main__":
    try:
        test_trend_backtest_accuracy_on_d()
        print("Тест точности бэктеста тренда: OK")
    except unittest.SkipTest as e:
        print("Пропущено:", e)
    except AssertionError as e:
        print("Ошибка:", e)
        sys.exit(1)
