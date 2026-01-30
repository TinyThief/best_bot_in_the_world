"""Точка входа: отчёт по бэктесту тренда (график точности). Запуск из корня: python bin/trend_backtest_report.py [--tf D] [--all]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.trend_backtest_report import main

if __name__ == "__main__":
    main()
