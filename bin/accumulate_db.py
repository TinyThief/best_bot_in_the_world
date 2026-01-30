"""Точка входа: накопление БД. Запуск из корня: python bin/accumulate_db.py"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.scripts.accumulate_db import main

if __name__ == "__main__":
    main()
