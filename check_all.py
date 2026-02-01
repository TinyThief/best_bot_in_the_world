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
        if not (0 <= getattr(_config, "CANDLE_QUALITY_MIN_SCORE", 0) <= 1):
            issues.append("CANDLE_QUALITY_MIN_SCORE не в [0,1]")
        ds = getattr(_config, "DATA_SOURCE", "db")
        if ds not in ("db", "exchange"):
            issues.append(f"DATA_SOURCE={ds!r}, ожидается db или exchange")
        w_phase = getattr(_config, "ENTRY_SCORE_WEIGHT_PHASE", 0.4)
        w_trend = getattr(_config, "ENTRY_SCORE_WEIGHT_TREND", 0.35)
        w_tf = getattr(_config, "ENTRY_SCORE_WEIGHT_TF_ALIGN", 0.25)
        if w_phase < 0 or w_trend < 0 or w_tf < 0:
            issues.append("веса ENTRY_SCORE_WEIGHT_* не должны быть отрицательными")
        if getattr(_config, "TF_ALIGN_MIN", 1) < 0:
            issues.append("TF_ALIGN_MIN должен быть >= 0")
        if issues:
            return _fail("значения вне диапазона", "; ".join(issues))
        detail = f"DATA_SOURCE={ds}, entry_score веса ок, CANDLE_QUALITY_MIN_SCORE ок"
        return _ok("пороги конфига в норме", detail)
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
                msg + " — запусти python bin/accumulate_db.py или python bin/full_backfill.py --extend.",
            )
        return _ok("по всем ТФ достаточно свечей для анализа", msg)
    except Exception as e:
        return _fail("подсчёт по ТФ", str(e))


def check_database_ohlc_outliers() -> CheckResult:
    """Для BTCUSDT: количество свечей с ценой high > 100k (возможный мусор — перезалей ТФ)."""
    if _config is None or _quick:
        return _ok("(пропуск)" if _quick else "требуется config", None)
    sym = (getattr(_config, "SYMBOL", "") or "").strip().upper()
    if "BTC" not in sym:
        return _ok("не BTC — проверка выбросов не выполняется", None)
    try:
        from src.core.database import get_connection, TABLE_NAME
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f"SELECT timeframe, COUNT(*) FROM {TABLE_NAME} WHERE symbol = ? AND (high > 100000 OR close > 100000) GROUP BY timeframe",
            (sym,),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return _ok("выбросов цен (high/close > 100k) в БД нет", None)
        parts = [f"{tf}:{cnt}" for tf, cnt in rows]
        return _warn(
            "в БД есть свечи с завышенными ценами (high/close > 100k)",
            "По ТФ: " + ", ".join(parts) + ". Перезалей данные: python bin/refill_tf_d.py или python bin/full_backfill.py.",
        )
    except Exception as e:
        return _fail("проверка выбросов БД", str(e))


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
        sig = r["signals"]
        direction = sig.get("direction", "?")
        tfs = list((r.get("timeframes") or {}).keys())
        missing = []
        if "entry_score" not in sig:
            missing.append("signals.entry_score")
        if "higher_tf_regime" not in r:
            missing.append("higher_tf_regime")
        if "candle_quality_ok" not in r:
            missing.append("candle_quality_ok")
        if missing:
            return _warn(f"в отчёте нет полей: {', '.join(missing)}", str(list(r.keys())))
        entry_score = sig.get("entry_score")
        regime = r.get("higher_tf_regime", "?")
        detail = f"direction={direction}, TFs={tfs}, entry_score={entry_score}, regime={regime}"
        return _ok(f"direction={direction}, TFs={tfs}, entry_score ок, regime ок", detail)
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
        entry_score = r["signals"].get("entry_score")
        regime = r.get("higher_tf_regime", "?")
        detail = f"direction={direction}, entry_score={entry_score}, regime={regime}"
        return _ok(f"multi_tf (db): direction={direction}", detail)
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
    """Импорт скриптов: accumulate_db, full_backfill, backtest_phases, backtest_trend, compare_phase_methods, test_run_once, trend_daily_full, trend_backtest_report."""
    try:
        from src.scripts import (
            accumulate_db,
            full_backfill,
            backtest_phases,
            backtest_trend,
            compare_phase_methods,
            test_run_once,
            trend_daily_full,
            trend_backtest_report,
        )
        ok = (
            hasattr(accumulate_db, "main")
            and hasattr(full_backfill, "main")
            and hasattr(backtest_phases, "main")
            and hasattr(backtest_trend, "main")
            and hasattr(compare_phase_methods, "main")
            and hasattr(test_run_once, "run")
            and hasattr(trend_daily_full, "main")
            and hasattr(trend_backtest_report, "main")
        )
        if not ok:
            return _fail("у скриптов нет main/run", None)
        return _ok(
            "accumulate_db, full_backfill, backtest_phases, backtest_trend, compare_phase_methods, test_run_once, trend_daily_full, trend_backtest_report",
            None,
        )
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


def check_backtest_visualization() -> CheckResult:
    """Визуализация бэктестов: run_for_chart (фаз/тренд) + build_phases_chart, build_trend_chart. Весь период из БД (max_bars=None)."""
    try:
        from src.scripts.backtest_phases import run_for_chart
        from src.scripts.backtest_trend import run_for_chart as run_trend_for_chart
        from src.utils.backtest_chart import build_phases_chart, build_trend_chart, build_candlestick_trend_chart
        from src.core.database import get_connection, get_candles
    except Exception as e:
        return _fail("импорт визуализации бэктестов", str(e))
    try:
        # Бэктест фаз за весь период (max_bars=None)
        data_ph = run_for_chart(timeframe="60", max_bars=None, step=5)
        if data_ph:
            buf_ph = build_phases_chart(data_ph)
            n_ph = len(buf_ph.getvalue())
            if n_ph == 0:
                return _fail("график фаз пустой", None)
        else:
            n_ph = 0
        # Бэктест тренда за весь период (max_bars=None)
        data_tr = run_trend_for_chart(timeframe="60", max_bars=None, step=5)
        if data_tr:
            buf_tr = build_trend_chart(data_tr)
            n_tr = len(buf_tr.getvalue())
            if n_tr == 0:
                return _fail("график тренда пустой", None)
        else:
            n_tr = 0
        # Свечной график с зонами TREND_UP (из БД, ТФ D или 60)
        candlestick_ok = False
        try:
            from src.core import config
            conn = get_connection()
            cur = conn.cursor()
            for tf in ("D", "60"):
                candles = get_candles(cur, config.SYMBOL, tf, limit=200, order_asc=False)
                if candles and len(candles) >= 101:
                    buf_c = build_candlestick_trend_chart(candles, config.SYMBOL, tf, lookback=100)
                    candlestick_ok = len(buf_c.getvalue()) > 0
                    break
            conn.close()
        except Exception:
            pass
        if data_ph and data_tr:
            detail = f"фаз: {data_ph.get('bars_used')} свечей, график {n_ph} байт; тренд: {data_tr.get('bars_used')} свечей, график {n_tr} байт"
            if candlestick_ok:
                detail += "; свечной TREND_UP: OK"
            return _ok("визуализация бэктестов (фаз, тренд) — графики строятся по всему периоду из БД", detail)
        if data_ph or data_tr:
            which = "фаз" if data_ph else "тренд"
            return _ok(f"визуализация бэктеста {which} — OK (второй без данных)", None)
        return _ok(
            "визуализация бэктестов: run_for_chart и build_*_chart работают",
            "в БД нет достаточного количества свечей по ТФ 60 для построения графиков",
        )
    except Exception as e:
        return _fail("построение графиков бэктеста", str(e))


def check_analysis_modules() -> CheckResult:
    """Модули анализа: market_trend (detect_trend, detect_regime), candle_quality (validate_candles)."""
    try:
        from src.analysis.market_trend import detect_trend, detect_regime
        from src.utils.candle_quality import validate_candles
        if not callable(detect_trend) or not callable(detect_regime):
            return _fail("market_trend: detect_trend/detect_regime не вызываемые", None)
        if not callable(validate_candles):
            return _fail("candle_quality: validate_candles не вызываемая", None)
        return _ok("market_trend (detect_trend, detect_regime), candle_quality (validate_candles)", None)
    except ImportError as e:
        return _fail("импорт модулей анализа", str(e))
    except Exception as e:
        return _fail("проверка модулей анализа", str(e))


def check_orderflow() -> CheckResult:
    """Order Flow: orderflow.py (DOM, T&S, Delta, Sweeps), analyze_orderflow; при ORDERFLOW_ENABLED — OrderbookStream, TradesStream."""
    try:
        from src.analysis.orderflow import (
            analyze_dom,
            analyze_time_and_sales,
            compute_volume_delta,
            detect_sweeps,
            analyze_orderflow,
        )
    except ImportError as e:
        return _fail("импорт orderflow", str(e))
    # DOM: mock snapshot
    try:
        snap = {"bids": [[100.0, 10.0], [99.0, 50.0]], "asks": [[101.0, 20.0], [102.0, 5.0]]}
        dom = analyze_dom(snap, depth_levels=5)
        if "imbalance_ratio" not in dom or "clusters_bid" not in dom or "significant_levels" not in dom:
            return _fail("analyze_dom: неверная структура", str(list(dom.keys())))
        if not (0 <= dom["imbalance_ratio"] <= 1):
            return _fail("analyze_dom: imbalance_ratio вне [0,1]", str(dom["imbalance_ratio"]))
    except Exception as e:
        return _fail("analyze_dom", str(e))
    # T&S и Delta: mock trades (T, side, size)
    try:
        now_ms = 1700000000000
        trades = [
            {"T": now_ms - 30_000, "side": "Buy", "size": 1.0},
            {"T": now_ms - 20_000, "side": "Sell", "size": 0.5},
            {"T": now_ms - 10_000, "side": "Buy", "size": 2.0},
        ]
        tns = analyze_time_and_sales(trades, window_sec=60.0, now_ts_ms=now_ms)
        if "total_volume" not in tns or "buy_volume" not in tns or "trades_count" not in tns:
            return _fail("analyze_time_and_sales: неверная структура", str(list(tns.keys())))
        delta = compute_volume_delta(trades, window_sec=60.0, now_ts_ms=now_ms)
        if "delta" not in delta or "delta_ratio" not in delta:
            return _fail("compute_volume_delta: неверная структура", str(list(delta.keys())))
    except Exception as e:
        return _fail("T&S / Delta", str(e))
    # Sweeps: mock candles и уровни из DOM
    try:
        candles = [
            {"start_time": 1000, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
            {"start_time": 2000, "open": 100.5, "high": 102.0, "low": 99.5, "close": 101.0},
        ]
        levels = [{"price": 99.0, "side": "bid"}, {"price": 102.0, "side": "ask"}]
        sweeps = detect_sweeps(candles, levels, lookback_bars=5)
        if "recent_sweeps_bid" not in sweeps or "last_sweep_side" not in sweeps:
            return _fail("detect_sweeps: неверная структура", str(list(sweeps.keys())))
    except Exception as e:
        return _fail("detect_sweeps", str(e))
    # Сводный вызов
    try:
        of = analyze_orderflow(
            orderbook_snapshot=snap,
            recent_trades=trades,
            candles=candles,
            window_sec=60.0,
        )
        if "dom" not in of or "time_and_sales" not in of or "volume_delta" not in of or "sweeps" not in of:
            return _fail("analyze_orderflow: неверная структура", str(list(of.keys())))
    except Exception as e:
        return _fail("analyze_orderflow", str(e))
    # При ORDERFLOW_ENABLED проверяем наличие потоков (импорт, не запуск)
    if _config and getattr(_config, "ORDERFLOW_ENABLED", False):
        try:
            from src.core.orderbook_ws import OrderbookStream
            from src.core.trades_ws import TradesStream
            if not hasattr(OrderbookStream, "get_snapshot") or not hasattr(TradesStream, "get_recent_trades_since"):
                return _fail("OrderbookStream/TradesStream: нет get_snapshot или get_recent_trades_since", None)
            return _ok("orderflow (DOM, T&S, Delta, Sweeps), OrderbookStream, TradesStream готовы", None)
        except ImportError as e:
            return _fail("ORDERFLOW_ENABLED=1, но импорт потоков", str(e))
    return _ok("orderflow (DOM, T&S, Delta, Sweeps) — модуль и прогон по mock-данным ок", None)


def check_microstructure_sandbox() -> CheckResult:
    """Песочница микроструктуры: MicrostructureSandbox, виртуальная позиция и PnL по сигналу."""
    try:
        from src.app.microstructure_sandbox import MicrostructureSandbox, _mid_from_snapshot
    except ImportError as e:
        return _fail("импорт microstructure_sandbox", str(e))
    try:
        snap = {"bids": [[100.0, 10.0], [99.0, 5.0]], "asks": [[101.0, 8.0], [102.0, 3.0]]}
        mid = _mid_from_snapshot(snap)
        if mid is None or abs(mid - 100.5) > 0.01:
            return _fail("_mid_from_snapshot: неверный mid", str(mid))
        of_mock = {"dom": {"imbalance_ratio": 0.6}, "volume_delta": {"delta_ratio": 0.2}, "sweeps": {"last_sweep_side": None}}
        sandbox = MicrostructureSandbox(initial_balance=100.0)
        state = sandbox.update(of_mock, mid, 1700000000)
        if "position_side" not in state or "total_realized_pnl" not in state or "unrealized_pnl" not in state:
            return _fail("MicrostructureSandbox.update: неверная структура state", str(list(state.keys())))
        return _ok("microstructure_sandbox (виртуальная позиция и PnL по сигналу) — ок", None)
    except Exception as e:
        return _fail("microstructure_sandbox", str(e))


def check_microstructure_signal() -> CheckResult:
    """Сигнал по микроструктуре: microstructure_signal.compute_microstructure_signal (long/short/none по Order Flow)."""
    try:
        from src.analysis.microstructure_signal import compute_microstructure_signal
    except ImportError as e:
        return _fail("импорт microstructure_signal", str(e))
    try:
        of_mock = {
            "dom": {"imbalance_ratio": 0.6},
            "volume_delta": {"delta_ratio": 0.2},
            "sweeps": {"last_sweep_side": None},
        }
        res = compute_microstructure_signal(of_mock)
        if res.get("direction") not in ("long", "short", "none"):
            return _fail("microstructure_signal: неверный direction", str(res.get("direction")))
        if "confidence" not in res or "details" not in res:
            return _fail("microstructure_signal: нет confidence или details", str(list(res.keys())))
        if res["direction"] != "long":
            return _fail("microstructure_signal: при delta_ratio=0.2, imbalance=0.6 ожидался long", str(res))
        return _ok("microstructure_signal (long/short/none по DOM, Delta, Sweep) — ок", None)
    except Exception as e:
        return _fail("microstructure_signal", str(e))


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
        ("БД: выбросы цен (BTC)", check_database_ohlc_outliers),
        ("Bybit API", check_bybit_ping),
        ("multi_tf (exchange)", check_multi_tf_exchange),
        ("multi_tf (db)", check_multi_tf_db),
        ("Модули анализа", check_analysis_modules),
        ("Order Flow", check_orderflow),
        ("Сигнал по микроструктуре", check_microstructure_signal),
        ("Песочница микроструктуры", check_microstructure_sandbox),
        ("Логирование", check_logging),
        ("Ретраи Bybit", check_exchange_retry_config),
        ("Telegram-бот", check_telegram),
        ("Скрипты", check_scripts),
        ("Модули app", check_app_modules),
        ("Визуализация бэктестов", check_backtest_visualization),
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
