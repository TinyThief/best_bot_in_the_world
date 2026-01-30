"""Один прогон анализа для теста. Запуск из корня: python bin/test_run_once.py"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.test_run_once import run

if __name__ == "__main__":
    run()
