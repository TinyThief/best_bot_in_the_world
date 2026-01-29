"""Точка входа: бэктест точности тренда. Запуск: python backtest_trend.py [--tf 60] [--bars 50000] [--min-strength 0.4]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.backtest_trend import main

if __name__ == "__main__":
    main()
