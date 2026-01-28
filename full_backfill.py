"""Точка входа: полный бэкфилл БД. Запуск: python full_backfill.py [--clear] [--extend]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.scripts.full_backfill import main

if __name__ == "__main__":
    main()
