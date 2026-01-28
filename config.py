"""
Конфигурация мультитаймфреймового бота для Bybit.
Все чувствительные данные — из переменных окружения (.env).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


# --- Bybit ---
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() in ("1", "true", "yes")
BYBIT_CATEGORY = os.getenv("BYBIT_CATEGORY", "linear")  # linear | inverse | spot

# --- Торговля ---
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")

# Таймфреймы для анализа: строка вида "15,60,240" или "1,5,15,60,D"
_tf_str = os.getenv("TIMEFRAMES", "15,60,240")
TIMEFRAMES = [t.strip() for t in _tf_str.split(",") if t.strip()]

# Лимит свечей на один запрос (Bybit: 1–1000)
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "200"))

# Интервал опроса (секунды) — как часто пересчитывать сигналы
POLL_INTERVAL_SEC = float(os.getenv("POLL_INTERVAL_SEC", "60"))

# --- База для обучения ---
# Путь к SQLite-файлу (папка создаётся автоматически)
DB_PATH = os.getenv("DB_PATH", "data/klines.db")
# Все таймфреймы для накопления: 1,3,5,15,30,60,120,240,360,720,D,W,M
_db_tf = os.getenv("TIMEFRAMES_DB", "1,3,5,15,30,60,120,240,360,720,D,W,M")
TIMEFRAMES_DB = [t.strip() for t in _db_tf.split(",") if t.strip()]
# Сколько свечей подгружать вглубь при первом бэкфилле (на один таймфрейм)
BACKFILL_MAX_CANDLES = int(os.getenv("BACKFILL_MAX_CANDLES", "50000"))
# Интервал обновления БД (секунды) — как часто дотягивать новые свечи
DB_UPDATE_INTERVAL_SEC = float(os.getenv("DB_UPDATE_INTERVAL_SEC", "60"))


def validate_config() -> list[str]:
    """Проверяет конфиг, возвращает список ошибок."""
    errors = []
    if not BYBIT_API_KEY and not BYBIT_API_SECRET:
        errors.append("Не заданы BYBIT_API_KEY и BYBIT_API_SECRET (для тестнет могут быть пустыми для только чтения)")
    if not SYMBOL:
        errors.append("SYMBOL не может быть пустым")
    if not TIMEFRAMES:
        errors.append("TIMEFRAMES должен содержать хотя бы один интервал (например 15,60,240)")
    return errors
