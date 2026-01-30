"""Скрипты: накопление БД, бэктест фаз/тренда, сравнение методов фаз, полный бэкфилл, тренд по БД D, отчёт по бэктесту тренда, тест-прогон."""
from . import accumulate_db
from . import backtest_phases
from . import backtest_trend
from . import compare_phase_methods
from . import full_backfill
from . import test_run_once
from . import trend_daily_full
from . import trend_backtest_report

__all__ = [
    "accumulate_db",
    "backtest_phases",
    "backtest_trend",
    "compare_phase_methods",
    "full_backfill",
    "test_run_once",
    "trend_daily_full",
    "trend_backtest_report",
]
