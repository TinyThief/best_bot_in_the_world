"""
Конфигурация мультитаймфреймового бота для Bybit.
Загрузка из .env через pydantic-settings с валидацией типов.
Чувствительные данные — только из переменных окружения.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта (src/core/config.py → parent.parent.parent)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _parse_list(s: str) -> list[str]:
    return [t.strip() for t in (s or "").split(",") if t.strip()]


def _parse_allowed_ids(s: str) -> list[int]:
    out: list[int] = []
    for part in (s or "").split(","):
        part = part.strip()
        if part and part.isdigit():
            out.append(int(part))
    return out


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Bybit ---
    BYBIT_API_KEY: str = ""
    BYBIT_API_SECRET: str = ""
    BYBIT_TESTNET: bool = True
    BYBIT_CATEGORY: str = "linear"

    # --- Торговля ---
    SYMBOL: str = "BTCUSDT"
    TIMEFRAMES: str = "15,60,240"
    KLINE_LIMIT: int = 200
    POLL_INTERVAL_SEC: float = 60.0
    # При ORDERFLOW_ENABLED использовать этот интервал опроса (быстрее, «здесь и сейчас»)
    POLL_INTERVAL_ORDERFLOW_SEC: float = 15.0
    # При SANDBOX_CONTEXT_NOW_ONLY (чисто проп-режим) — ещё чаще, событийная реакция (3 с)
    POLL_INTERVAL_PROP_SEC: float = 3.0
    ORDERBOOK_LIMIT: int = 25  # глубина стакана (bid/ask) для get_orderbook; linear: 1–500

    # --- Order Flow (микроструктура: DOM, T&S, Delta, Sweeps) ---
    ORDERFLOW_ENABLED: bool = False  # при True в main запускаются OrderbookStream и TradesStream, результат в отчёте
    ORDERFLOW_WINDOW_SEC: float = 60.0  # окно для T&S и Volume Delta (сек)
    ORDERFLOW_SHORT_WINDOW_SEC: float = 20.0  # короткое окно «последний импульс» для context_now (0 = выкл)
    # websocket-client требует ping_interval > ping_timeout
    ORDERFLOW_WS_PING_INTERVAL: int = 30  # интервал ping (сек); должен быть больше ping_timeout
    ORDERFLOW_WS_PING_TIMEOUT: int = 20  # таймаут ожидания pong (сек); меньше ping_interval
    ORDERFLOW_SAVE_TO_DB: bool = False  # при True метрики Order Flow пишутся в таблицу orderflow_metrics (та же БД)
    MICROSTRUCTURE_SANDBOX_ENABLED: bool = False  # при True виртуальная торговля по сигналу микроструктуры (песочница)
    SANDBOX_INITIAL_BALANCE: float = 100.0  # стартовый виртуальный баланс в USD для песочницы микроструктуры
    SANDBOX_TAKER_FEE: float = 0.0006  # комиссия биржи (taker), доля от объёма; 0.0006 = 0.06% (Bybit linear)
    SANDBOX_MIN_CONFIDENCE: float = 0.75  # минимальная уверенность сигнала для входа (0..1); выше = меньше сделок, комиссия не съедает депозит
    SANDBOX_COOLDOWN_SEC: int = 300  # секунд после выхода до разрешения нового входа; снижает «пинг-понг»
    SANDBOX_MIN_HOLD_SEC: int = 120  # минимум секунд удержания позиции перед разрешением выхода по микроструктуре
    SANDBOX_EXIT_NONE_TICKS: int = 4  # тиков подряд с сигналом none/против — тогда закрыть; больше = меньше шума
    SANDBOX_EXIT_MIN_CONFIDENCE: float = 0.0  # выход при confidence ниже порога (0 = не использовать); трейлинг по микроструктуре
    SANDBOX_MIN_CONFIRMING_TICKS: int = 0  # минимум тиков «в нашу сторону» после входа перед разрешением выхода (0 = выкл)
    SANDBOX_EXIT_WINDOW_TICKS: int = 0  # размер окна для выхода: последние M тиков (0 = только N подряд)
    SANDBOX_EXIT_WINDOW_NEED: int = 0  # сколько из последних M тиков должны быть «на выход» (при EXIT_WINDOW_TICKS > 0)
    SANDBOX_STOP_LOSS_PCT: float = 0.0  # стоп-лосс в % от entry (0 = выкл); выход по цене
    SANDBOX_BREAKEVEN_TRIGGER_PCT: float = 0.0  # при прибыли >= этого % перенести SL в безубыток (0 = выкл)
    SANDBOX_TAKE_PROFIT_PCT: float = 0.0  # тейк-профит в % от entry (0 = выкл); при пустом SANDBOX_TP_LEVELS
    SANDBOX_TP_LEVELS: str = ""  # частичный TP: "0.2:40,0.35:60" = на 0.2% закрыть 40%, на 0.35% — остаток; пусто = один TP по SANDBOX_TAKE_PROFIT_PCT
    SANDBOX_TRAIL_TRIGGER_PCT: float = 0.0  # при прибыли >= этого % включить трейлинг остатка (0 = выкл)
    SANDBOX_TRAIL_PCT: float = 0.0  # откат от пика прибыли в % — закрыть по трейлингу (0 = выкл)
    SANDBOX_MIN_PROFIT_PCT: float = 0.2  # при выходе по микроструктуре в плюсе: не закрывать, пока профит < этого % (0 = выкл)
    SANDBOX_NO_OPEN_SAME_TICK_AS_CLOSE: bool = True  # не открывать позицию в тот же тик, что и закрытие (избежать мгновенного разворота)
    SANDBOX_NO_OPEN_SWEEP_ONLY: bool = True  # не открывать, когда сигнал даёт по сути только sweep (защита от ловушек)
    SANDBOX_SWEEP_DELAY_SEC: int = 20  # секунд после последнего sweep до разрешения входа (0 = выкл); снижает вход «в лоб» по sweep'у
    SANDBOX_TREND_FILTER: bool = True  # True = не открывать позицию против тренда старшего ТФ (long только при не bearish, short при не bullish)
    SANDBOX_LEVERAGE_MIN: float = 1.0  # минимальное плечо (1 = без плеча)
    SANDBOX_LEVERAGE_MAX: float = 5.0  # максимальное плечо при адаптивном расчёте
    SANDBOX_ADAPTIVE_LEVERAGE: bool = True  # True = плечо от уверенности сигнала и просадки
    SANDBOX_MARGIN_FRACTION: float = 0.95  # доля эквити под маржу (0.95 = 95%); notional = margin * leverage
    SANDBOX_LIQUIDATION_MAINTENANCE: float = 1.0  # ликвидация при убытке >= margin_used * это (1.0 = полная маржа)
    SANDBOX_DRAWDOWN_LEVERAGE_PCT: float = 10.0  # при просадке от пика выше % — снижать макс. плечо вдвое
    MICROSTRUCTURE_MIN_SCORE: float = 0.35  # минимальный |score| для long/short в сигнале; выше = чаще none, меньше лишних входов
    # «Здесь и сейчас»: контекст по уровню + flow за короткое окно (как проп-трейдеры)
    CONTEXT_NOW_LEVEL_DISTANCE_PCT: float = 0.0015  # цена в пределах этой доли от уровня = «у уровня» (0.0015 = 0.15%)
    CONTEXT_NOW_DELTA_RATIO_MIN: float = 0.12  # порог delta_ratio в коротком окне для flow_bullish/flow_bearish
    CONTEXT_NOW_USE_DOM_LEVELS: bool = False  # True = at_support/at_resistance по уровням стакана (DOM), иначе по trading_zones
    SANDBOX_USE_CONTEXT_NOW_PRIMARY: bool = False  # True = вход только при at_support+flow_bullish / at_resistance+flow_bearish
    SANDBOX_CONTEXT_NOW_ONLY: bool = False  # True = направление только из context_now (без сигнала микроструктуры), чисто проп-режим

    # --- Фазы ---
    PHASE_SCORE_MIN: float = 0.6
    PHASE_UNCLEAR_THRESHOLD: float = 0.5
    PHASE_MIN_GAP: float = 0.1
    PHASE_STABILITY_MIN: float = 0.6
    PHASE_HISTORY_SIZE: int = 5

    # --- Тренд ---
    TREND_STRENGTH_MIN: float = 0.35
    TREND_UNCLEAR_THRESHOLD: float = 0.3
    TREND_MIN_GAP: float = 0.08
    TREND_FLAT_WHEN_RANGE: bool = True  # в боковике (ADX < 20) чаще возвращать flat
    TREND_MIN_GAP_DOWN: float = 0.0     # мин. разрыв для "вниз" (0.10 = строже, меньше ложных down)
    TREND_USE_PROFILES: bool = True     # адаптация по ТФ (short/long): lookback, min_gap, min_gap_down
    TREND_REGIME_WEIGHTING: bool = True  # учёт режима рынка: в trend — выше вес структуры/EMA, в range — ниже
    TREND_SURGE_PENALTY: float = 0.0   # в режиме surge умножать bull/bear (0 = выкл; 0.88 = чаще flat)
    TREND_CONFIRM_UP: bool = False      # для «вверх» требовать подтверждение от +DI/-DI или структуры (True = строже)
    TREND_LOW_VOLUME_THRESHOLD: float = 0.7   # при volume_ratio ниже — штраф (TREND_LOW_VOLUME_PENALTY)
    TREND_LOW_VOLUME_PENALTY: float = 0.0    # множитель bull/bear при низком объёме (0 = выкл; 0.9 = чаще flat)
    TREND_MIN_AGREEMENT: int = 0       # минимум согласований из трёх (структура, EMA, +DI/-DI) для up/down (0 = выкл; 2 = строго)

    # --- Торговые зоны ---
    TRADING_ZONES_MAX_LEVELS: int = 0  # макс. уровней в выдаче: 0 = все найденные зоны, >0 = топ N по силе

    # --- Фильтры входа ---
    VOLUME_MIN_RATIO: float = 0.0
    ATR_MAX_RATIO: float = 0.0
    TF_ALIGN_MIN: int = 1
    TREND_STABILITY_MIN: float = 0.0
    LEVEL_MAX_DISTANCE_PCT: float = 0.0
    REGIME_BLOCK_SURGE: bool = True
    ENTRY_SCORE_WEIGHT_PHASE: float = 0.4
    ENTRY_SCORE_WEIGHT_TREND: float = 0.35
    ENTRY_SCORE_WEIGHT_TF_ALIGN: float = 0.25
    CANDLE_QUALITY_MIN_SCORE: float = 0.0

    # --- Источник данных и ретраи ---
    DATA_SOURCE: Literal["db", "exchange"] = "db"
    SIGNAL_MIN_CONFIDENCE: float = 0.0
    EXCHANGE_MAX_RETRIES: int = 5
    EXCHANGE_RETRY_BACKOFF_SEC: float = 1.0
    EXCHANGE_REQUEST_TIMEOUT_SEC: int = 30  # таймаут одного запроса к Bybit (по умолчанию 30 с, в pybit 10)

    # --- База для обучения ---
    DB_PATH: str = ""
    TIMEFRAMES_DB: str = "1,3,5,15,30,60,120,240,360,720,D,W,M"
    BACKFILL_MAX_CANDLES: int = 50000
    DB_UPDATE_INTERVAL_SEC: float = 60.0
    AUTO_EXTEND_AT_STARTUP: bool = True
    # Исторические данные для бэктеста (тики, стакан): пусто = data/history в корне проекта
    HISTORY_DATA_DIR: str = ""

    # --- Логирование ---
    LOG_DIR: str = ""
    LOG_LEVEL: str = "INFO"
    LOG_LEVEL_FILE: str = ""
    LOG_FILE_MAX_MB: float = 10.0
    LOG_BACKUP_COUNT: int = 7
    LOG_SIGNALS_FILE: bool = True

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_IDS: str = ""
    TELEGRAM_ALERT_CHAT_ID: str = ""
    TELEGRAM_ALERT_ON_SIGNAL_CHANGE: bool = False
    TELEGRAM_ALERT_INTERVAL_SEC: float = 90.0
    TELEGRAM_ALERT_MIN_CONFIDENCE: float = 0.0

    @field_validator("LOG_LEVEL", "LOG_LEVEL_FILE", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return (v or "").strip().upper()

    @field_validator("DATA_SOURCE", mode="before")
    @classmethod
    def _data_source(cls, v: str) -> str:
        s = (v or "db").strip().lower()
        return s if s in ("db", "exchange") else "db"


_settings = _Settings()

# --- Экспорт в модуль (обратная совместимость: from src.core import config; config.SYMBOL) ---
BYBIT_API_KEY = _settings.BYBIT_API_KEY
BYBIT_API_SECRET = _settings.BYBIT_API_SECRET
BYBIT_TESTNET = _settings.BYBIT_TESTNET
BYBIT_CATEGORY = _settings.BYBIT_CATEGORY
SYMBOL = _settings.SYMBOL
TIMEFRAMES = _parse_list(_settings.TIMEFRAMES)
KLINE_LIMIT = _settings.KLINE_LIMIT
POLL_INTERVAL_SEC = _settings.POLL_INTERVAL_SEC
POLL_INTERVAL_ORDERFLOW_SEC = _settings.POLL_INTERVAL_ORDERFLOW_SEC
POLL_INTERVAL_PROP_SEC = _settings.POLL_INTERVAL_PROP_SEC
PHASE_SCORE_MIN = _settings.PHASE_SCORE_MIN
PHASE_UNCLEAR_THRESHOLD = _settings.PHASE_UNCLEAR_THRESHOLD
PHASE_MIN_GAP = _settings.PHASE_MIN_GAP
PHASE_STABILITY_MIN = _settings.PHASE_STABILITY_MIN
PHASE_HISTORY_SIZE = _settings.PHASE_HISTORY_SIZE
TREND_STRENGTH_MIN = _settings.TREND_STRENGTH_MIN
TREND_UNCLEAR_THRESHOLD = _settings.TREND_UNCLEAR_THRESHOLD
TREND_MIN_GAP = _settings.TREND_MIN_GAP
TREND_FLAT_WHEN_RANGE = _settings.TREND_FLAT_WHEN_RANGE
TREND_MIN_GAP_DOWN = _settings.TREND_MIN_GAP_DOWN
TREND_USE_PROFILES = _settings.TREND_USE_PROFILES
TREND_REGIME_WEIGHTING = _settings.TREND_REGIME_WEIGHTING
TREND_SURGE_PENALTY = _settings.TREND_SURGE_PENALTY
TREND_CONFIRM_UP = _settings.TREND_CONFIRM_UP
TREND_LOW_VOLUME_THRESHOLD = _settings.TREND_LOW_VOLUME_THRESHOLD
TREND_LOW_VOLUME_PENALTY = _settings.TREND_LOW_VOLUME_PENALTY
TREND_MIN_AGREEMENT = _settings.TREND_MIN_AGREEMENT
TRADING_ZONES_MAX_LEVELS = _settings.TRADING_ZONES_MAX_LEVELS
VOLUME_MIN_RATIO = _settings.VOLUME_MIN_RATIO
ATR_MAX_RATIO = _settings.ATR_MAX_RATIO
TF_ALIGN_MIN = _settings.TF_ALIGN_MIN
TREND_STABILITY_MIN = _settings.TREND_STABILITY_MIN
LEVEL_MAX_DISTANCE_PCT = _settings.LEVEL_MAX_DISTANCE_PCT
REGIME_BLOCK_SURGE = _settings.REGIME_BLOCK_SURGE
ENTRY_SCORE_WEIGHT_PHASE = _settings.ENTRY_SCORE_WEIGHT_PHASE
ENTRY_SCORE_WEIGHT_TREND = _settings.ENTRY_SCORE_WEIGHT_TREND
ENTRY_SCORE_WEIGHT_TF_ALIGN = _settings.ENTRY_SCORE_WEIGHT_TF_ALIGN
CANDLE_QUALITY_MIN_SCORE = _settings.CANDLE_QUALITY_MIN_SCORE
ORDERFLOW_ENABLED = _settings.ORDERFLOW_ENABLED
ORDERFLOW_WINDOW_SEC = _settings.ORDERFLOW_WINDOW_SEC
ORDERFLOW_SHORT_WINDOW_SEC = _settings.ORDERFLOW_SHORT_WINDOW_SEC
ORDERFLOW_WS_PING_INTERVAL = _settings.ORDERFLOW_WS_PING_INTERVAL
ORDERFLOW_WS_PING_TIMEOUT = _settings.ORDERFLOW_WS_PING_TIMEOUT
ORDERFLOW_SAVE_TO_DB = _settings.ORDERFLOW_SAVE_TO_DB
MICROSTRUCTURE_SANDBOX_ENABLED = _settings.MICROSTRUCTURE_SANDBOX_ENABLED
SANDBOX_INITIAL_BALANCE = _settings.SANDBOX_INITIAL_BALANCE
SANDBOX_TAKER_FEE = _settings.SANDBOX_TAKER_FEE
SANDBOX_MIN_CONFIDENCE = _settings.SANDBOX_MIN_CONFIDENCE
SANDBOX_COOLDOWN_SEC = _settings.SANDBOX_COOLDOWN_SEC
SANDBOX_MIN_HOLD_SEC = _settings.SANDBOX_MIN_HOLD_SEC
SANDBOX_EXIT_NONE_TICKS = _settings.SANDBOX_EXIT_NONE_TICKS
SANDBOX_EXIT_MIN_CONFIDENCE = _settings.SANDBOX_EXIT_MIN_CONFIDENCE
SANDBOX_MIN_CONFIRMING_TICKS = _settings.SANDBOX_MIN_CONFIRMING_TICKS
SANDBOX_EXIT_WINDOW_TICKS = _settings.SANDBOX_EXIT_WINDOW_TICKS
SANDBOX_EXIT_WINDOW_NEED = _settings.SANDBOX_EXIT_WINDOW_NEED
SANDBOX_STOP_LOSS_PCT = _settings.SANDBOX_STOP_LOSS_PCT
SANDBOX_BREAKEVEN_TRIGGER_PCT = _settings.SANDBOX_BREAKEVEN_TRIGGER_PCT
SANDBOX_TAKE_PROFIT_PCT = _settings.SANDBOX_TAKE_PROFIT_PCT
SANDBOX_TP_LEVELS = _settings.SANDBOX_TP_LEVELS
SANDBOX_TRAIL_TRIGGER_PCT = _settings.SANDBOX_TRAIL_TRIGGER_PCT
SANDBOX_TRAIL_PCT = _settings.SANDBOX_TRAIL_PCT
SANDBOX_MIN_PROFIT_PCT = _settings.SANDBOX_MIN_PROFIT_PCT
SANDBOX_NO_OPEN_SAME_TICK_AS_CLOSE = _settings.SANDBOX_NO_OPEN_SAME_TICK_AS_CLOSE
SANDBOX_NO_OPEN_SWEEP_ONLY = _settings.SANDBOX_NO_OPEN_SWEEP_ONLY
SANDBOX_SWEEP_DELAY_SEC = _settings.SANDBOX_SWEEP_DELAY_SEC
CONTEXT_NOW_LEVEL_DISTANCE_PCT = _settings.CONTEXT_NOW_LEVEL_DISTANCE_PCT
CONTEXT_NOW_DELTA_RATIO_MIN = _settings.CONTEXT_NOW_DELTA_RATIO_MIN
CONTEXT_NOW_USE_DOM_LEVELS = _settings.CONTEXT_NOW_USE_DOM_LEVELS
SANDBOX_USE_CONTEXT_NOW_PRIMARY = _settings.SANDBOX_USE_CONTEXT_NOW_PRIMARY
SANDBOX_CONTEXT_NOW_ONLY = _settings.SANDBOX_CONTEXT_NOW_ONLY
SANDBOX_TREND_FILTER = _settings.SANDBOX_TREND_FILTER
SANDBOX_LEVERAGE_MIN = _settings.SANDBOX_LEVERAGE_MIN
SANDBOX_LEVERAGE_MAX = _settings.SANDBOX_LEVERAGE_MAX
SANDBOX_ADAPTIVE_LEVERAGE = _settings.SANDBOX_ADAPTIVE_LEVERAGE
SANDBOX_MARGIN_FRACTION = _settings.SANDBOX_MARGIN_FRACTION
SANDBOX_LIQUIDATION_MAINTENANCE = _settings.SANDBOX_LIQUIDATION_MAINTENANCE
SANDBOX_DRAWDOWN_LEVERAGE_PCT = _settings.SANDBOX_DRAWDOWN_LEVERAGE_PCT
MICROSTRUCTURE_MIN_SCORE = _settings.MICROSTRUCTURE_MIN_SCORE
DATA_SOURCE = _settings.DATA_SOURCE
SIGNAL_MIN_CONFIDENCE = _settings.SIGNAL_MIN_CONFIDENCE
EXCHANGE_MAX_RETRIES = _settings.EXCHANGE_MAX_RETRIES
EXCHANGE_RETRY_BACKOFF_SEC = _settings.EXCHANGE_RETRY_BACKOFF_SEC
EXCHANGE_REQUEST_TIMEOUT_SEC = _settings.EXCHANGE_REQUEST_TIMEOUT_SEC
DB_PATH = _settings.DB_PATH.strip() or str(PROJECT_ROOT / "data" / "klines.db")
TIMEFRAMES_DB = _parse_list(_settings.TIMEFRAMES_DB)
BACKFILL_MAX_CANDLES = _settings.BACKFILL_MAX_CANDLES
DB_UPDATE_INTERVAL_SEC = _settings.DB_UPDATE_INTERVAL_SEC
AUTO_EXTEND_AT_STARTUP = _settings.AUTO_EXTEND_AT_STARTUP
_history_dir = (_settings.HISTORY_DATA_DIR or "").strip()
HISTORY_DATA_DIR: Path = Path(_history_dir) if _history_dir else PROJECT_ROOT / "data" / "history"
LOG_DIR = Path(_settings.LOG_DIR.strip()) if _settings.LOG_DIR.strip() else PROJECT_ROOT / "logs"
LOG_LEVEL = _settings.LOG_LEVEL or "INFO"
LOG_LEVEL_FILE = (_settings.LOG_LEVEL_FILE or "").strip() or LOG_LEVEL
LOG_FILE_MAX_MB = _settings.LOG_FILE_MAX_MB
LOG_BACKUP_COUNT = _settings.LOG_BACKUP_COUNT
LOG_SIGNALS_FILE = _settings.LOG_SIGNALS_FILE
TELEGRAM_BOT_TOKEN = _settings.TELEGRAM_BOT_TOKEN.strip()
TELEGRAM_ALLOWED_IDS = _parse_allowed_ids(_settings.TELEGRAM_ALLOWED_IDS)
_alert_chat = (_settings.TELEGRAM_ALERT_CHAT_ID or "").strip()
TELEGRAM_ALERT_CHAT_ID: int | None = int(_alert_chat) if _alert_chat.isdigit() else None
TELEGRAM_ALERT_ON_SIGNAL_CHANGE = _settings.TELEGRAM_ALERT_ON_SIGNAL_CHANGE
TELEGRAM_ALERT_INTERVAL_SEC = _settings.TELEGRAM_ALERT_INTERVAL_SEC or 90.0
TELEGRAM_ALERT_MIN_CONFIDENCE = _settings.TELEGRAM_ALERT_MIN_CONFIDENCE or 0.0


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
