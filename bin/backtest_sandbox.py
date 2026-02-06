"""Точка входа: бэктест песочницы микроструктуры по историческим тикам. Запуск из корня: python bin/backtest_sandbox.py --from 2025-01-01 --to 2025-12-31 [--symbol BTCUSDT] [--tick-sec 15] [--window-sec 60]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.backtest_sandbox import main

if __name__ == "__main__":
    main()
