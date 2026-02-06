"""Скрипты: накопление БД, бэктест фаз/тренда/песочницы, сравнение методов фаз, полный бэкфилл, тренд по БД D, отчёт по бэктесту тренда/песочницы, тест-прогон."""
from . import accumulate_db
from . import backtest_phases
from . import backtest_sandbox
from . import backtest_trend
from . import compare_phase_methods
from . import full_backfill
from . import sandbox_backtest_report
from . import test_run_once
from . import trend_daily_full
from . import trend_backtest_report

__all__ = [
    "accumulate_db",
    "backtest_phases",
    "backtest_sandbox",
    "backtest_trend",
    "compare_phase_methods",
    "full_backfill",
    "sandbox_backtest_report",
    "test_run_once",
    "trend_daily_full",
    "trend_backtest_report",
]
