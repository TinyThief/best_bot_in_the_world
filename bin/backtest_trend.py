"""Точка входа: бэктест точности тренда. Запуск из корня: python bin/backtest_trend.py [--tf 60] [--bars 50000]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.backtest_trend import main

if __name__ == "__main__":
    main()
