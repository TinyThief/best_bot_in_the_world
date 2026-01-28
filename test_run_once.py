"""Один прогон анализа для теста. Запуск: python test_run_once.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.test_run_once import run

if __name__ == "__main__":
    run()
