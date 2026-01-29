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
# Ниже этого score фаза считается «неясной» (phase_unclear=True), не использовать для входа.
PHASE_UNCLEAR_THRESHOLD = float(os.getenv("PHASE_UNCLEAR_THRESHOLD", "0.5"))
# Минимальный разрыв между основной и второй фазой (score_gap). Меньше — фаза пограничная, осторожно.
PHASE_MIN_GAP = float(os.getenv("PHASE_MIN_GAP", "0.1"))
# Минимальная доля последних тиков с той же фазой для «устойчивости» (phase_stable). 0..1.
PHASE_STABILITY_MIN = float(os.getenv("PHASE_STABILITY_MIN", "0.6"))
# Размер истории фаз по ТФ для расчёта stability (число тиков).
PHASE_HISTORY_SIZE = int(os.getenv("PHASE_HISTORY_SIZE", "5"))

# --- Тренд (модуль market_trend) ---
# Минимальная сила тренда (0..1) для учёта в решении. Ниже — flat или осторожно.
TREND_STRENGTH_MIN = float(os.getenv("TREND_STRENGTH_MIN", "0.35"))
# Ниже этого strength тренд считается неясным (trend_unclear=True).
TREND_UNCLEAR_THRESHOLD = float(os.getenv("TREND_UNCLEAR_THRESHOLD", "0.3"))
# Минимальный разрыв между основным и вторым направлением (strength_gap).
TREND_MIN_GAP = float(os.getenv("TREND_MIN_GAP", "0.08"))

# Фильтры входа (0 = отключено): объём относительно MA(vol), ATR относительно MA(ATR)
# VOLUME_MIN_RATIO: разрешать вход только если vol_ratio >= N (например 0.8). 0 = не проверять.
VOLUME_MIN_RATIO = float(os.getenv("VOLUME_MIN_RATIO", "0"))
# ATR_MAX_RATIO: не входить если ATR > N * MA(ATR) (экстремальная волатильность). 0 = не проверять.
ATR_MAX_RATIO = float(os.getenv("ATR_MAX_RATIO", "0"))
# Минимум таймфреймов, совпадающих по тренду и фазе с направлением входа (1 = только старший, 2+ = консенсус).
TF_ALIGN_MIN = int(os.getenv("TF_ALIGN_MIN", "1"))
# Устойчивость тренда: доля последних тиков с тем же направлением (0 = не проверять). Аналогично PHASE_STABILITY_MIN.
TREND_STABILITY_MIN = float(os.getenv("TREND_STABILITY_MIN", "0"))
# Уровни: разрешать вход только если цена в пределах N (доля, например 0.02 = 2%) от свинг-поддержки или сопротивления. 0 = не проверять.
LEVEL_MAX_DISTANCE_PCT = float(os.getenv("LEVEL_MAX_DISTANCE_PCT", "0"))
# Режим рынка (тренд/диапазон/всплеск): 1 = не входить при режиме «всплеск» по старшему ТФ.
REGIME_BLOCK_SURGE = os.getenv("REGIME_BLOCK_SURGE", "1").lower() in ("1", "true", "yes")

# Единый score входа (0..1): веса фазы, тренда и совпадения ТФ. Сумма весов может быть любой — score нормализуется.
ENTRY_SCORE_WEIGHT_PHASE = float(os.getenv("ENTRY_SCORE_WEIGHT_PHASE", "0.4"))
ENTRY_SCORE_WEIGHT_TREND = float(os.getenv("ENTRY_SCORE_WEIGHT_TREND", "0.35"))
ENTRY_SCORE_WEIGHT_TF_ALIGN = float(os.getenv("ENTRY_SCORE_WEIGHT_TF_ALIGN", "0.25"))

# Качество свечей: минимальный quality_score (0..1) для использования ТФ в анализе; 0 = не проверять.
CANDLE_QUALITY_MIN_SCORE = float(os.getenv("CANDLE_QUALITY_MIN_SCORE", "0"))

# Источник свечей для анализа: "db" — из локальной БД (меньше запросов к бирже), "exchange" — каждый тик с Bybit.
_ds = os.getenv("DATA_SOURCE", "db").strip().lower()
DATA_SOURCE = _ds if _ds in ("db", "exchange") else "db"
# Минимальная уверенность сигнала (0..1): ниже — «слабый» сигнал (в логах/фильтрах). Порог для будущих авто-сделок.
SIGNAL_MIN_CONFIDENCE = float(os.getenv("SIGNAL_MIN_CONFIDENCE", "0"))
# Ретраи запросов к Bybit: макс попыток, базовая задержка (с) при rate limit / сетевой ошибке
EXCHANGE_MAX_RETRIES = int(os.getenv("EXCHANGE_MAX_RETRIES", "5"))
EXCHANGE_RETRY_BACKOFF_SEC = float(os.getenv("EXCHANGE_RETRY_BACKOFF_SEC", "1"))

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
