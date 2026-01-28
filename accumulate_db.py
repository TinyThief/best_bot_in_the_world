"""Точка входа: накопление БД. Запуск: python accumulate_db.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.scripts.accumulate_db import main

if __name__ == "__main__":
    main()
