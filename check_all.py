"""Скрипт проверки: конфиг, БД, multi_tf, telegram import. Запуск: python check_all.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

def ok(msg: str) -> None:
    print("[OK]", msg)

def fail(msg: str, e: Exception | None = None) -> None:
    print("[FAIL]", msg, file=sys.stderr)
    if e:
        print(" ", e, file=sys.stderr)

errors = 0

# 1. Конфиг
print("1. Config...")
try:
    from src.core import config
    from src.core.config import validate_config
    assert config.SYMBOL, "SYMBOL пуст"
    assert config.TIMEFRAMES, "TIMEFRAMES пуст"
    validate_config()  # может вернуть предупреждения — это ок
    ok("config + validate_config")
except Exception as e:
    fail("config", e)
    errors += 1

# 2. БД
print("2. Database...")
try:
    from src.core.database import get_connection, count_candles
    conn = get_connection()
    cur = conn.cursor()
    n = count_candles(cur, symbol=config.SYMBOL)
    conn.close()
    ok(f"database connect, count_candles({config.SYMBOL}) = {n}")
except Exception as e:
    fail("database", e)
    errors += 1

# 3. Один прогон multi_tf (exchange + market_phases)
print("3. Multi-TF analysis (exchange + market_phases)...")
try:
    from src.analysis.multi_tf import analyze_multi_timeframe
    r = analyze_multi_timeframe()
    assert "signals" in r and "timeframes" in r
    ok(f"analyze_multi_timeframe: direction={r['signals']['direction']}, TFs={list(r['timeframes'].keys())}")
except Exception as e:
    fail("multi_tf / exchange", e)
    errors += 1

# 4. Telegram: импорт и проверка токена
print("4. Telegram bot (import + token)...")
try:
    from src.app import telegram_bot
    has_run = hasattr(telegram_bot, "run_bot")
    from src.core import config as c
    has_token = bool(c.TELEGRAM_BOT_TOKEN)
    if has_run and has_token:
        ok("telegram_bot.run_bot exists, TELEGRAM_BOT_TOKEN set")
    elif has_run:
        ok("telegram_bot.run_bot exists (token not set — fill .env for /start)")
    else:
        fail("telegram_bot.run_bot not found")
        errors += 1
except Exception as e:
    fail("telegram_bot import", e)
    errors += 1

# 5. Accumulate_db и full_backfill — импорт
print("5. accumulate_db / full_backfill (import)...")
try:
    from src.scripts import accumulate_db, full_backfill
    ok("accumulate_db.main, full_backfill.main importable")
except Exception as e:
    fail("accumulate_db/full_backfill", e)
    errors += 1

# 6. backtest_phases и test_run_once — импорт
print("6. backtest_phases / test_run_once (import)...")
try:
    from src.scripts import backtest_phases, test_run_once
    assert hasattr(backtest_phases, "main") and hasattr(test_run_once, "run")
    ok("backtest_phases.main, test_run_once.run importable")
except Exception as e:
    fail("backtest_phases/test_run_once", e)
    errors += 1

print()
if errors:
    print(f"Итого: {errors} ошибок")
    sys.exit(1)
print("Итого: всё проверено, ошибок нет.")
sys.exit(0)
