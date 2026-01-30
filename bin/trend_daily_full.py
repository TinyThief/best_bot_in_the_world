"""Точка входа: тренд по всей БД ТФ D с визуализацией. Запуск из корня: python bin/trend_daily_full.py [--output путь.png]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.trend_daily_full import main

if __name__ == "__main__":
    main()
