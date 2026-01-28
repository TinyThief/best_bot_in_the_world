"""
Точка входа мультитаймфреймового торгового бота для Bybit.
Режимы: анализ (только логи) / в будущем — торговля по сигналам.
"""
import logging
import time

import config
from config import validate_config
from multi_tf import analyze_multi_timeframe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_once() -> None:
    """Один проход: мультитаймфреймовый анализ и вывод результата."""
    report = analyze_multi_timeframe()
    logger.info(
        "Сигнал: %s | Причина: %s | Старший ТФ тренд: %s",
        report["signals"]["direction"],
        report["signals"]["reason"],
        report["higher_tf_trend"],
    )
    for tf, data in report.get("timeframes", {}).items():
        trend = data.get("trend", "?")
        n = len(data.get("candles", []))
        logger.info("  ТФ %s: тренд=%s, свечей=%s", tf, trend, n)


def main() -> None:
    errs = validate_config()
    if errs:
        for e in errs:
            logger.warning("Конфиг: %s", e)
        # Для теста без ключей всё равно можно крутить анализ по публичным свечам
        logger.info("Запуск в режиме только чтения (без сделок)")

    logger.info(
        "Старт бота | пара=%s | таймфреймы=%s | интервал опроса=%s с",
        config.SYMBOL,
        config.TIMEFRAMES,
        config.POLL_INTERVAL_SEC,
    )
    try:
        while True:
            run_once()
            time.sleep(config.POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        logger.info("Остановка по Ctrl+C")


if __name__ == "__main__":
    main()
