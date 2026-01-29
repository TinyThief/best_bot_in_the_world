"""Скрипты: накопление БД, бэктест фаз, сравнение методов фаз, полный бэкфилл, тест-прогон."""
from . import accumulate_db
from . import backtest_phases
from . import compare_phase_methods
from . import full_backfill
from . import test_run_once

__all__ = [
    "accumulate_db",
    "backtest_phases",
    "compare_phase_methods",
    "full_backfill",
    "test_run_once",
]
