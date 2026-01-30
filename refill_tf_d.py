"""Точка входа: перезалив дневного ТФ (D) с биржи.

Запуск (из корня проекта):
  python refill_tf_d.py   # если python в PATH
  py -3 refill_tf_d.py   # Windows: лаунчер Python
  путь\к\python.exe refill_tf_d.py   # полный путь к интерпретатору
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.scripts.refill_tf_d import main

if __name__ == "__main__":
    main()
