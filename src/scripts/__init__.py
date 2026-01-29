"""Скрипты: накопление БД, бэктест фаз, бэктест тренда, сравнение методов фаз, полный бэкфилл, тест-прогон."""
from . import accumulate_db
from . import backtest_phases
from . import backtest_trend
from . import compare_phase_methods
from . import full_backfill
from . import test_run_once

__all__ = [
    "accumulate_db",
    "backtest_phases",
    "backtest_trend",
    "compare_phase_methods",
    "full_backfill",
    "test_run_once",
]
