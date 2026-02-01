"""
Бэктест сценария управления сделкой на одном году (по умолчанию 2025).

Сигнал: тренд по одному ТФ (detect_trend) — long при up, exit_long при down.
Управление сделкой: TP/SL (фикс %, трейлинг или ATR) + опционально time_stop.
Загружает свечи из БД, фильтрует по году, прогоняет backtest_engine.

Режимы:
  Один ТФ: --tf 60 (по умолчанию) — сводка и список сделок.
  Все ТФ:  --all-tf — прогон по каждому ТФ из TIMEFRAMES_DB за год, сводная таблица.

Запуск: python bin/backtest_trade_2025.py [--year 2025] [--tf 60] [--tp-sl trailing]
        python bin/backtest_trade_2025.py --all-tf --year 2025
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Any

from ..core import config
from ..core.database import get_connection, get_candles
from ..analysis.market_trend import detect_trend
from ..utils.backtest_engine import run_backtest
from ..utils.tp_sl import (
    FixedTPSL,
    make_trailing_handler,
    make_atr_trailing_handler,
)


def _default_lookback(timeframe: str) -> int:
    """
    Окно для сигнала по умолчанию в зависимости от ТФ.
    Для W и M заданы так, чтобы хватало одного года данных: в году 52 недели, 12 месяцев.
    """
    tf = str(timeframe).strip().upper()
    if tf == "M":
        return 6   # в году 12 месяцев → нужно минимум 7 свечей
    if tf == "W":
        return 26  # в году 52 недели → нужно минимум 27 свечей
    if tf == "D":
        return 100
    try:
        m = int(tf)
        return 80 if m <= 30 else 120
    except ValueError:
        return 120


def _year_ts_ms(year: int) -> tuple[int, int]:
    """Возвращает (start_ms, end_ms) для года в UTC (мс)."""
    start_ms = int(datetime(year, 1, 1, 0, 0, 0).timestamp() * 1000)
    end_ms = int(datetime(year + 1, 1, 1, 0, 0, 0).timestamp() * 1000)
    return start_ms, end_ms


def _filter_candles_by_year(candles: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    """Оставляет только свечи с start_time в заданном году (UTC)."""
    start_ms, end_ms = _year_ts_ms(year)
    return [c for c in candles if start_ms <= c.get("start_time", 0) < end_ms]


def _signal_fn_trend(
    window: list[dict[str, Any]],
    bar_index: int,
    candles: list[dict[str, Any]],
    timeframe: str,
    min_strength: float = 0.0,
) -> str:
    """
    Сигнал по тренду: long при up (и strength >= min_strength), exit_long при down, иначе none.
    """
    res = detect_trend(window, timeframe=timeframe)
    direction = res.get("direction", "flat")
    strength = res.get("strength", 0.0)
    if direction == "up" and strength >= min_strength:
        return "long"
    if direction == "down":
        return "exit_long"
    return "none"


def run(
    year: int = 2025,
    symbol: str | None = None,
    timeframe: str = "60",
    lookback: int = 120,
    tp_sl_mode: str = "trailing",
    tp_pct: float = 0.04,
    sl_pct: float = 0.02,
    max_bars_in_position: int | None = None,
    initial_deposit: float = 100.0,
    min_strength: float = 0.0,
) -> dict[str, Any]:
    """
    Загружает свечи из БД, оставляет только год, прогоняет бэктест сценария управления сделкой.
    Возвращает результат run_backtest + год и число свечей за год.
    """
    symbol = symbol or config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    candles_all = get_candles(cur, symbol, timeframe, limit=None, order_asc=True)
    conn.close()

    candles = _filter_candles_by_year(candles_all, year)
    if len(candles) < lookback + 1:
        return {
            "error": f"За {year} год свечей: {len(candles)}, нужно минимум {lookback + 1}",
            "year": year,
            "symbol": symbol,
            "timeframe": timeframe,
            "n_candles_year": len(candles),
        }

    def signal_fn(w: list[dict], i: int, c: list[dict], tf: str) -> str:
        return _signal_fn_trend(w, i, c, tf, min_strength=min_strength)

    tp_sl_handler = None
    if tp_sl_mode == "fixed":
        tp_sl_handler = FixedTPSL(tp_pct=tp_pct, sl_pct=sl_pct)
    elif tp_sl_mode == "trailing":
        tp_sl_handler = make_trailing_handler()
    elif tp_sl_mode == "atr":
        tp_sl_handler = make_atr_trailing_handler()

    result = run_backtest(
        candles,
        lookback,
        signal_fn,
        timeframe=timeframe,
        tp_pct=tp_pct if tp_sl_mode == "fixed" else None,
        sl_pct=sl_pct if tp_sl_mode == "fixed" else None,
        tp_sl_handler=tp_sl_handler,
        initial_deposit=initial_deposit,
        max_bars_in_position=max_bars_in_position,
    )
    result["year"] = year
    result["symbol"] = symbol
    result["timeframe"] = timeframe
    result["n_candles_year"] = len(candles)
    result["tp_sl_mode"] = tp_sl_mode
    return result


def _ts_to_str(ts_ms: int) -> str:
    """Форматирует метку времени (мс) в строку даты."""
    try:
        s = ts_ms / 1000 if ts_ms > 1e10 else ts_ms
        return datetime.utcfromtimestamp(s).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts_ms)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Бэктест сценария управления сделкой (сигнал + TP/SL) на данных одного года"
    )
    parser.add_argument("--year", type=int, default=2025, help="Год данных (по умолчанию 2025)")
    parser.add_argument("--symbol", default=None, help="Пара (по умолчанию из .env)")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default="60", help="Таймфрейм при одном ТФ (по умолчанию 60)")
    parser.add_argument("--all-tf", action="store_true", dest="all_tf", help="Прогнать по всем ТФ из TIMEFRAMES_DB за год, вывести сводную таблицу")
    parser.add_argument("--lookback", type=int, default=None, help="Окно для сигнала (по умолчанию: по ТФ при --all-tf, 120 при одном ТФ)")
    parser.add_argument(
        "--tp-sl",
        dest="tp_sl_mode",
        choices=("fixed", "trailing", "atr"),
        default="trailing",
        help="Режим TP/SL: fixed (%%), trailing, atr (по умолчанию trailing)",
    )
    parser.add_argument("--tp-pct", type=float, default=0.04, help="Тейк-профит в %% при fixed (по умолчанию 4%%)")
    parser.add_argument("--sl-pct", type=float, default=0.02, help="Стоп-лосс в %% при fixed (по умолчанию 2%%)")
    parser.add_argument(
        "--max-bars",
        type=int,
        default=None,
        dest="max_bars_in_position",
        help="Макс. баров в позиции (time_stop), без лимита если не задано",
    )
    parser.add_argument("--deposit", type=float, default=100.0, help="Начальный депозит (по умолчанию 100)")
    parser.add_argument("--min-strength", type=float, default=0.0, help="Мин. strength тренда для входа (0 = без фильтра)")
    args = parser.parse_args()

    if args.all_tf:
        _main_all_tf(args)
        return

    lookback = args.lookback if args.lookback is not None else 120
    result = run(
        year=args.year,
        symbol=args.symbol or config.SYMBOL,
        timeframe=args.timeframe,
        lookback=lookback,
        tp_sl_mode=args.tp_sl_mode,
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        max_bars_in_position=args.max_bars_in_position,
        initial_deposit=args.deposit,
        min_strength=args.min_strength,
    )

    if result.get("error"):
        print(result["error"], file=sys.stderr)
        sys.exit(1)

    n_candles = result.get("n_candles_year", 0)
    n_trades = result.get("n_trades", 0)
    initial = result.get("initial_deposit", 0)
    final = result.get("final_equity", 0)
    max_dd = result.get("max_drawdown_pct", 0)
    trades = result.get("trades", [])

    print("=" * 60)
    print("Бэктест сценария управления сделкой | год {}".format(result.get("year", args.year)))
    print("=" * 60)
    print("Пара: {}, ТФ: {}, год: {}".format(result.get("symbol"), result.get("timeframe"), result.get("year")))
    print("Свечей за год: {}, окно: {}, TP/SL: {}".format(n_candles, lookback, args.tp_sl_mode))
    print()
    print("Депозит: {:.2f}  →  Итог: {:.2f}  (доходность: {:.1f}%)".format(
        initial, final, (final - initial) / initial * 100 if initial else 0
    ))
    print("Сделок: {}, макс. просадка: {:.1f}%".format(n_trades, max_dd))
    print()

    if trades:
        print("--- Сделки (вход / выход) ---")
        buys = [t for t in trades if t.get("side") == "buy"]
        sells = [t for t in trades if t.get("side") == "sell"]
        for i, (b, s) in enumerate(zip(buys, sells)):
            entry_ts = _ts_to_str(b.get("time", 0))
            exit_ts = _ts_to_str(s.get("time", 0))
            reason = s.get("exit_reason", "?")
            pnl = s.get("pnl_pct", 0)
            print("  {}  вход {}  выход {}  причина={}  PnL={:+.2f}%".format(i + 1, entry_ts, exit_ts, reason, pnl))
        if len(buys) != len(sells):
            print("  (последняя позиция открыта до конца периода)")
    print()
    print("Готово.")


def run_all_tf_for_chart(
    year: int = 2025,
    symbol: str | None = None,
    tp_sl_mode: str = "trailing",
    tp_pct: float = 0.04,
    sl_pct: float = 0.02,
    max_bars_in_position: int | None = None,
    initial_deposit: float = 100.0,
    min_strength: float = 0.0,
    lookback: int | None = None,
) -> list[dict[str, Any]]:
    """
    Прогон бэктеста сценария управления сделкой по всем ТФ из TIMEFRAMES_DB за год.
    Возвращает список результатов (без вывода в консоль). Для графиков в Telegram.
    """
    timeframes = getattr(config, "TIMEFRAMES_DB", ["15", "60", "240"])
    if isinstance(timeframes, str):
        timeframes = [s.strip() for s in timeframes.split(",") if s.strip()]
    symbol = symbol or config.SYMBOL
    results: list[dict[str, Any]] = []
    for tf in timeframes:
        lb = lookback if lookback is not None else _default_lookback(tf)
        result = run(
            year=year,
            symbol=symbol,
            timeframe=tf,
            lookback=lb,
            tp_sl_mode=tp_sl_mode,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            max_bars_in_position=max_bars_in_position,
            initial_deposit=initial_deposit,
            min_strength=min_strength,
        )
        if result.get("error"):
            continue
        results.append(result)
    return results


def _main_all_tf(args: argparse.Namespace) -> None:
    """Прогон по всем ТФ из TIMEFRAMES_DB за год, сводная таблица."""
    results = run_all_tf_for_chart(
        year=args.year,
        symbol=args.symbol or config.SYMBOL,
        tp_sl_mode=args.tp_sl_mode,
        tp_pct=args.tp_pct,
        sl_pct=args.sl_pct,
        max_bars_in_position=args.max_bars_in_position,
        initial_deposit=args.deposit,
        min_strength=args.min_strength,
        lookback=args.lookback,
    )
    if not results:
        print("Нет результатов ни по одному ТФ (нет данных за год?).", file=sys.stderr)
        sys.exit(1)

    symbol = args.symbol or config.SYMBOL
    print("=" * 72)
    print("Бэктест сценария управления сделкой | все ТФ | год {}".format(args.year))
    print("=" * 72)
    print("Пара: {}, TP/SL: {}, депозит: {}".format(symbol, args.tp_sl_mode, args.deposit))
    print()
    print("{:>4}  {:>8}  {:>6}  {:>12}  {:>8}  {:>10}".format(
        "ТФ", "свечей", "сделок", "итог", "дох.%", "макс.DD%"
    ))
    print("-" * 72)
    for r in results:
        tf = r.get("timeframe", "?")
        n_candles = r.get("n_candles_year", 0)
        n_trades = r.get("n_trades", 0)
        initial = r.get("initial_deposit", 0)
        final = r.get("final_equity", 0)
        ret_pct = (final - initial) / initial * 100 if initial else 0
        max_dd = r.get("max_drawdown_pct", 0)
        print("{:>4}  {:>8}  {:>6}  {:>12.2f}  {:>+7.1f}%  {:>9.1f}%".format(
            tf, n_candles, n_trades, final, ret_pct, max_dd
        ))
    print()
    print("Готово.")


if __name__ == "__main__":
    main()
