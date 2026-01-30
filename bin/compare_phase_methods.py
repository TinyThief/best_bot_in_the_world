"""Точка входа: сравнение методов фаз (Wyckoff, индикаторы, PA). Запуск из корня: python bin/compare_phase_methods.py"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.compare_phase_methods import main

if __name__ == "__main__":
    main()
