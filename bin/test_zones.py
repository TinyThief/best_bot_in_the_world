"""Тест торговых зон. Запуск из корня: python bin/test_zones.py [TF] [limit]"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.scripts.test_zones import run

if __name__ == "__main__":
    tf = sys.argv[1] if len(sys.argv) > 1 else "240"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    run(tf=tf, limit=limit)
