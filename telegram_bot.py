"""Точка входа: Telegram-бот для управления. Запуск: python telegram_bot.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.core.logging_config import setup_logging

if __name__ == "__main__":
    setup_logging()
    try:
        from src.app.telegram_bot import run_bot
        run_bot()
    except RuntimeError as e:
        print("\nОшибка:", e, file=sys.stderr)
        print("\nЧто сделать:", file=sys.stderr)
        print("  1. Открой @BotFather в Telegram, создай бота (/newbot), скопируй токен.", file=sys.stderr)
        print("  2. В .env добавь строку: TELEGRAM_BOT_TOKEN=твой_токен", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        if "telegram" in str(e).lower():
            print("\nНе найден модуль python-telegram-bot. Установи: pip install python-telegram-bot", file=sys.stderr)
        else:
            print("ImportError:", e, file=sys.stderr)
        sys.exit(1)
