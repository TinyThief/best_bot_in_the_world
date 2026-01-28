"""Точка входа: мультитаймфреймовый бот. Запуск: python main.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app.main import main

if __name__ == "__main__":
    main()
