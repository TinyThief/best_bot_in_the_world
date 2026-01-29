"""Точка входа: сравнение методов определения фазы (Wyckoff, индикаторы, PA). Запуск: python compare_phase_methods.py [--tf 60] [--bars 20000]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.compare_phase_methods import main

if __name__ == "__main__":
    main()
