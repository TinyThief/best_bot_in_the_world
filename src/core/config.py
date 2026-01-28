"""
Конфигурация мультитаймфреймового бота для Bybit.
Все чувствительные данные — из переменных окружения (.env).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Корень проекта (src/core/config.py → parent.parent.parent)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_env_path = PROJECT_ROOT / ".env"
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

# Минимальный score фазы (0..1) для использования в торговом решении. Ниже — не открываем сделку по фазе.
# Детектор выдаёт максимум 0.7 для markup/markdown, 0.6 для recovery/accumulation/distribution; 0.8+ только у сильной капитуляции.
PHASE_SCORE_MIN = float(os.getenv("PHASE_SCORE_MIN", "0.6"))

# --- База для обучения ---
_db_path_env = os.getenv("DB_PATH")
DB_PATH = _db_path_env if _db_path_env else str(PROJECT_ROOT / "data" / "klines.db")
# Все таймфреймы для накопления: 1,3,5,15,30,60,120,240,360,720,D,W,M
_db_tf = os.getenv("TIMEFRAMES_DB", "1,3,5,15,30,60,120,240,360,720,D,W,M")
TIMEFRAMES_DB = [t.strip() for t in _db_tf.split(",") if t.strip()]
# Сколько свечей подгружать вглубь при первом бэкфилле (на один таймфрейм)
BACKFILL_MAX_CANDLES = int(os.getenv("BACKFILL_MAX_CANDLES", "50000"))
# Интервал обновления БД (секунды) — как часто дотягивать новые свечи
DB_UPDATE_INTERVAL_SEC = float(os.getenv("DB_UPDATE_INTERVAL_SEC", "60"))
# При подготовке БД автоматически углублять историю по всем ТФ, пока подгружаются свечи (0/1)
AUTO_EXTEND_AT_STARTUP = os.getenv("AUTO_EXTEND_AT_STARTUP", "1").strip().lower() in ("1", "true", "yes")

# --- Логирование ---
_log_dir = os.getenv("LOG_DIR", "").strip()
LOG_DIR = Path(_log_dir) if _log_dir else PROJECT_ROOT / "logs"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
LOG_LEVEL_FILE = os.getenv("LOG_LEVEL_FILE", "").strip().upper() or LOG_LEVEL
# Ротация: размер одного файла (МБ), число старых файлов
LOG_FILE_MAX_MB = float(os.getenv("LOG_FILE_MAX_MB", "10"))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "7"))
# Писать ли отдельный компактный лог сигналов (logs/signals.log)
LOG_SIGNALS_FILE = os.getenv("LOG_SIGNALS_FILE", "1").strip().lower() in ("1", "true", "yes")

# --- Telegram (управление ботом) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_allowed = os.getenv("TELEGRAM_ALLOWED_IDS", "").strip()
TELEGRAM_ALLOWED_IDS: list[int] = []
for s in _allowed.split(","):
    s = s.strip()
    if s and s.isdigit():
        TELEGRAM_ALLOWED_IDS.append(int(s))


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
