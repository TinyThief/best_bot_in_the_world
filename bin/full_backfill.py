"""Точка входа: полный бэкфилл БД. Запуск из корня: python bin/full_backfill.py [--clear] [--extend]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.scripts.full_backfill import main

if __name__ == "__main__":
    main()
