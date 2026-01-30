r"""Точка входа: перезалив дневного ТФ (D) с биржи. Запуск из корня: python bin/refill_tf_d.py"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.scripts.refill_tf_d import main

if __name__ == "__main__":
    main()
