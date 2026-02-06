"""Лаунчер: отчёт по бэктесту песочницы из sandbox_trades.csv. Запуск из корня: python bin/sandbox_backtest_report.py [--year 2025]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.sandbox_backtest_report import main

if __name__ == "__main__":
    main()
