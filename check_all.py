"""
Полная проверка окружения и компонентов торгового бота.
Запуск: python check_all.py [--quick] [-v]
  --quick  пропустить сетевые проверки (Bybit) и часть проверок БД
  -v       подробный вывод (тайминги, детали)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Результат одной проверки: (успех, краткое сообщение, детали для -v)
CheckResult = tuple[bool, str, str | None]

# Глобальные флаги (заполняются в main после парсинга)
_quick = False
_verbose = False
_config = None  # подставляется после первого успешного импорта config


def _ok(msg: str, detail: str | None = None) -> CheckResult:
    return (True, msg, detail)


def _fail(msg: str, detail: str | None = None) -> CheckResult:
    return (False, msg, detail)


def _warn(msg: str, detail: str | None = None) -> CheckResult:
    return (True, f"⚠ {msg}", detail)


def check_env_file() -> CheckResult:
    """Существует ли .env в корне проекта."""
    root = Path(__file__).resolve().parent
    env_path = root / ".env"
    if not env_path.exists():
        return _warn(".env не найден", "Скопируй .env.example в .env и заполни переменные.")
    return _ok(".env найден", str(env_path))


def check_config() -> CheckResult:
    """Загрузка конфига, SYMBOL, TIMEFRAMES, validate_config."""
    global _config
    try:
        from src.core import config
        from src.core.config import validate_config
        _config = config
        if not config.SYMBOL:
            return _fail("SYMBOL пуст", "Задай SYMBOL в .env")
        if not config.TIMEFRAMES:
            return _fail("TIMEFRAMES пуст", "Задай TIMEFRAMES в .env, например 15,60,240")
        errs = validate_config()
        detail = f"SYMBOL={config.SYMBOL}, TIMEFRAMES={config.TIMEFRAMES}"
        if errs:
            detail += "; предупреждения: " + "; ".join(errs[:3])
        return _ok("config загружен, validate_config ок", detail)
    except Exception as e:
        return _fail("ошибка загрузки config", str(e))


def check_config_bounds() -> CheckResult:
    """Пороги и флаги в допустимых границах."""
    if _config is None:
        return _fail("сначала проверь config", None)
    try:
        issues = []
        if not (0 <= getattr(_config, "PHASE_SCORE_MIN", 0.6) <= 1):
            issues.append("PHASE_SCORE_MIN не в [0,1]")
        if not (0 <= getattr(_config, "SIGNAL_MIN_CONFIDENCE", 0) <= 1):
            issues.append("SIGNAL_MIN_CONFIDENCE не в [0,1]")
        ds = getattr(_config, "DATA_SOURCE", "db")
        if ds not in ("db", "exchange"):
            issues.append(f"DATA_SOURCE={ds!r}, ожидается db или exchange")
        if issues:
            return _fail("значения вне диапазона", "; ".join(issues))
        return _ok("PHASE_SCORE_MIN, SIGNAL_MIN_CONFIDENCE, DATA_SOURCE в норме", f"DATA_SOURCE={ds}")
    except Exception as e:
        return _fail("проверка порогов", str(e))


def check_data_source_tfs() -> CheckResult:
    """При DATA_SOURCE=db все TIMEFRAMES должны быть в TIMEFRAMES_DB."""
    if _config is None:
        return _ok("(пропуск)", None)
    ds = getattr(_config, "DATA_SOURCE", "db")
    if ds != "db":
        return _ok("DATA_SOURCE=exchange, проверка ТФ не нужна", None)
    tfs = set(getattr(_config, "TIMEFRAMES", []) or [])
    db_tfs = set(getattr(_config, "TIMEFRAMES_DB", []) or [])
    missing = tfs - db_tfs
    if missing:
        return _warn(
            f"для анализа нужны ТФ {sorted(missing)}, их нет в TIMEFRAMES_DB",
            "Добавь их в TIMEFRAMES_DB в .env или анализ будет без этих ТФ при чтении из БД.",
        )
    return _ok("все TIMEFRAMES есть в TIMEFRAMES_DB", f"{sorted(tfs)} ⊆ {sorted(db_tfs)}")


def check_database() -> CheckResult:
    """Подключение к БД и общее количество свечей."""
    if _config is None:
        return _fail("сначала проверь config", None)
    try:
        from src.core.database import get_connection, count_candles, get_db_path
        conn = get_connection()
        cur = conn.cursor()
        n = count_candles(cur, symbol=_config.SYMBOL)
        path = get_db_path()
        conn.close()
        return _ok(f"БД доступна, свечей по {_config.SYMBOL}: {n}", str(path))
    except Exception as e:
        return _fail("БД", str(e))


def check_database_per_tf() -> CheckResult:
    """По каждому ТФ из TIMEFRAMES количество свечей в БД (при DATA_SOURCE=db нужны хотя бы 30)."""
    if _config is None or _quick:
        return _ok("(пропуск)" if _quick else "требуется config", None)
    ds = getattr(_config, "DATA_SOURCE", "db")
    if ds != "db":
        return _ok("DATA_SOURCE=exchange", None)
    try:
        from src.core.database import get_connection, count_candles
        conn = get_connection()
        cur = conn.cursor()
        min_need = 30  # минимум для detect_phase
        parts = []
        all_ok = True
        for tf in (getattr(_config, "TIMEFRAMES", []) or []):
            cnt = count_candles(cur, symbol=_config.SYMBOL, timeframe=tf)
            parts.append(f"{tf}:{cnt}")
            if cnt < min_need:
                all_ok = False
        conn.close()
        msg = ", ".join(parts)
        if not all_ok:
            return _warn(
                f"по одному или нескольким ТФ меньше {min_need} свечей",
                msg + " — запусти accumulate_db или full_backfill --extend.",
            )
        return _ok("по всем ТФ достаточно свечей для анализа", msg)
    except Exception as e:
        return _fail("подсчёт по ТФ", str(e))


def check_bybit_ping() -> CheckResult:
    """Один запрос к Bybit (get_kline limit=1) — доступность API."""
    if _config is None or _quick:
        return _ok("(пропуск)" if _quick else "требуется config", None)
    try:
        from src.core.exchange import get_klines
        tf = (_config.TIMEFRAMES or ["15"])[0]
        candles = get_klines(symbol=_config.SYMBOL, interval=tf, limit=1)
        n = len(candles) if candles else 0
        return _ok(f"Bybit API отвечает, tf={tf}, получено свечей: {n}", None)
    except Exception as e:
        return _fail("Bybit API недоступен", str(e))


def check_multi_tf_exchange() -> CheckResult:
    """Один прогон analyze_multi_timeframe без БД (данные с биржи)."""
    if _config is None:
        return _fail("сначала проверь config", None)
    try:
        from src.analysis.multi_tf import analyze_multi_timeframe
        r = analyze_multi_timeframe()  # без db_conn → exchange при наличии DATA_SOURCE
        if "signals" not in r or "timeframes" not in r:
            return _fail("неожиданная структура ответа", str(list(r.keys())))
        direction = r["signals"].get("direction", "?")
        tfs = list((r.get("timeframes") or {}).keys())
        confidence = r["signals"].get("confidence")
        detail = f"direction={direction}, TFs={tfs}"
        if confidence is not None:
            detail += f", confidence={confidence}"
        return _ok(f"direction={direction}, TFs={tfs}", detail)
    except Exception as e:
        return _fail("multi_tf / exchange", str(e))


def check_multi_tf_db() -> CheckResult:
    """Один прогон analyze_multi_timeframe с чтением из БД (если DATA_SOURCE=db)."""
    if _config is None or _quick:
        return _ok("(пропуск)" if _quick else "требуется config", None)
    if getattr(_config, "DATA_SOURCE", "db") != "db":
        return _ok("DATA_SOURCE=exchange", None)
    try:
        from src.core.database import get_connection
        from src.analysis.multi_tf import analyze_multi_timeframe
        conn = get_connection()
        r = analyze_multi_timeframe(db_conn=conn)
        conn.close()
        if "signals" not in r:
            return _fail("multi_tf(db): неверная структура", str(list(r.keys())))
        direction = r["signals"].get("direction", "?")
        return _ok(f"multi_tf (db): direction={direction}", None)
    except Exception as e:
        return _fail("multi_tf из БД", str(e))


def check_logging() -> CheckResult:
    """Импорт setup_logging и get_signals_logger; при -v — вызов setup и проверка каталога логов."""
    try:
        from src.core.logging_config import setup_logging, get_signals_logger
        get_signals_logger()  # проверка, что логгер создаётся
        if _verbose and _config:
            setup_logging()
            log_dir = getattr(_config, "LOG_DIR", None)
            if log_dir is not None:
                p = Path(log_dir) if not isinstance(log_dir, Path) else log_dir
                return _ok("logging_config ок, LOG_DIR создан" if p.exists() else "logging_config ок", str(p))
        return _ok("setup_logging, get_signals_logger импортируются", None)
    except Exception as e:
        return _fail("logging_config", str(e))


def check_telegram() -> CheckResult:
    """Модуль telegram_bot и токен."""
    try:
        from src.app import telegram_bot
        from src.core import config as c
        has_run = hasattr(telegram_bot, "run_bot")
        has_token = bool(getattr(c, "TELEGRAM_BOT_TOKEN", ""))
        if not has_run:
            return _fail("telegram_bot.run_bot не найден", None)
        if has_token:
            return _ok("telegram_bot.run_bot есть, TELEGRAM_BOT_TOKEN задан", None)
        return _warn("токен не задан — для /start заполни TELEGRAM_BOT_TOKEN в .env", None)
    except Exception as e:
        return _fail("импорт telegram_bot", str(e))


def check_scripts() -> CheckResult:
    """Импорт скриптов: accumulate_db, full_backfill, backtest_phases, test_run_once."""
    try:
        from src.scripts import accumulate_db, full_backfill, backtest_phases, test_run_once
        ok = (
            hasattr(accumulate_db, "main")
            and hasattr(full_backfill, "main")
            and hasattr(backtest_phases, "main")
            and hasattr(test_run_once, "run")
        )
        if not ok:
            return _fail("у скриптов нет main/run", None)
        return _ok("accumulate_db, full_backfill, backtest_phases, test_run_once", None)
    except Exception as e:
        return _fail("импорт скриптов", str(e))


def check_app_modules() -> CheckResult:
    """Импорт db_sync и bot_loop."""
    try:
        from src.app import db_sync, bot_loop
        has_sync = all(hasattr(db_sync, x) for x in ("open_and_prepare", "refresh_if_due", "close"))
        has_loop = hasattr(bot_loop, "run_one_tick")
        if not (has_sync and has_loop):
            return _fail("нет нужных функций в db_sync/bot_loop", None)
        return _ok("db_sync, bot_loop импортируются", None)
    except Exception as e:
        return _fail("импорт app-модулей", str(e))


def check_exchange_retry_config() -> CheckResult:
    """Наличие настроек ретраев в конфиге."""
    if _config is None:
        return _ok("(пропуск)", None)
    try:
        r = getattr(_config, "EXCHANGE_MAX_RETRIES", 5)
        b = getattr(_config, "EXCHANGE_RETRY_BACKOFF_SEC", 1.0)
        if r < 1 or b <= 0:
            return _warn("EXCHANGE_MAX_RETRIES или EXCHANGE_RETRY_BACKOFF_SEC некорректны", f"retries={r}, backoff={b}")
        return _ok("параметры ретраев заданы", f"retries={r}, backoff={b}s")
    except Exception as e:
        return _fail("проверка ретраев", str(e))


def run_check(name: str, fn: Callable[[], CheckResult]) -> tuple[bool, str, str | None, float]:
    """Запускает проверку, возвращает (ok, msg, detail, elapsed_sec)."""
    start = time.perf_counter()
    try:
        ok, msg, detail = fn()
    except Exception as e:
        ok, msg, detail = False, "исключение", str(e)
    elapsed = time.perf_counter() - start
    return (ok, msg, detail, elapsed)


def main() -> int:
    global _quick, _verbose
    ap = argparse.ArgumentParser(description="Проверка окружения и компонентов бота")
    ap.add_argument("--quick", action="store_true", help="Пропустить сетевые и часть проверок БД")
    ap.add_argument("-v", "--verbose", action="store_true", help="Подробный вывод и тайминги")
    args = ap.parse_args()
    _quick = args.quick
    _verbose = args.verbose

    checks = [
        ("Файл .env", check_env_file),
        ("Конфиг", check_config),
        ("Пороги конфига", check_config_bounds),
        ("ТФ для DATA_SOURCE=db", check_data_source_tfs),
        ("БД", check_database),
        ("БД по таймфреймам", check_database_per_tf),
        ("Bybit API", check_bybit_ping),
        ("multi_tf (exchange)", check_multi_tf_exchange),
        ("multi_tf (db)", check_multi_tf_db),
        ("Логирование", check_logging),
        ("Ретраи Bybit", check_exchange_retry_config),
        ("Telegram-бот", check_telegram),
        ("Скрипты", check_scripts),
        ("Модули app", check_app_modules),
    ]

    print("Проверка окружения бота" + (" (--quick)" if _quick else "") + (" -v" if _verbose else ""))
    print("=" * (50 if not _verbose else 70))

    total_start = time.perf_counter()
    fails = 0
    warns = 0

    for name, fn in checks:
        ok, msg, detail, elapsed = run_check(name, fn)
        tag = "[OK]   " if ok and not msg.startswith("⚠") else "[WARN] " if ok else "[FAIL] "
        line = f"{tag} {name}: {msg}"
        if _verbose and elapsed > 0.001:
            line += f"  ({elapsed:.2f}s)"
        print(line)
        if _verbose and detail:
            print("       " + detail.replace("\n", "\n       "))
        if not ok:
            fails += 1
        elif msg.startswith("⚠"):
            warns += 1

    total_elapsed = time.perf_counter() - total_start
    print("=" * (50 if not _verbose else 70))
    if _verbose:
        print(f"Время: {total_elapsed:.2f} с")
    if fails:
        print(f"Итого: {fails} ошибок, {warns} предупреждений. Исправь ошибки и запусти снова.")
        return 1
    if warns:
        print(f"Итого: всё проверено, {warns} предупреждений. Бот должен работать.")
    else:
        print("Итого: всё проверено, ошибок нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
