"""Точка входа: бэктест сценария управления сделкой на одном году (по умолчанию 2025). Запуск из корня: python bin/backtest_trade_2025.py [--year 2025] [--tf 60] [--tp-sl trailing]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.backtest_trade_2025 import main

if __name__ == "__main__":
    main()
