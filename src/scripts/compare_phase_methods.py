"""
Сравнение трёх методов определения фазы рынка: Wyckoff, индикаторы, price action (BOS/CHOCH).

Загружает свечи из БД, прогоняет каждый метод по одним и тем же окнам,
считает точность по направлению (бычьи/медвежьи фазы vs форвард-доходность) и выводит сводку.

Запуск: python compare_phase_methods.py [--tf 60] [--bars 20000] [--step 5]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Any, Callable

from ..core import config
from ..core.database import get_connection, get_candles
from ..analysis.market_phases import BEARISH_PHASES, BULLISH_PHASES, PHASE_NAMES_RU
from ..analysis.phase_wyckoff import detect_phase as detect_phase_wyckoff
from ..analysis.phase_indicators import detect_phase as detect_phase_indicators
from ..analysis.phase_structure import detect_phase as detect_phase_structure


def _run_one_method(
    candles: list[dict[str, Any]],
    symbol: str,
    timeframe: str,
    lookback: int,
    forward_bars: int,
    step: int,
    threshold_up: float,
    threshold_down: float,
    detect_phase_fn: Callable[..., dict[str, Any]],
    min_score: float = 0.0,
) -> tuple[dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Один прогон бэктеста для одного метода detect_phase."""
    returns_by_phase: dict[str, list[tuple[float, float]]] = defaultdict(list)
    n = len(candles)
    kwargs: dict[str, Any] = {"lookback": lookback, "timeframe": timeframe}

    for i in range(lookback, n - forward_bars + 1, step):
        window = candles[i - lookback : i]
        res = detect_phase_fn(window, **kwargs)
        phase = res["phase"]
        score = res.get("score", 0.0)
        price_now = candles[i]["close"]
        price_fwd = candles[i + forward_bars - 1]["close"]
        if price_now <= 0:
            continue
        ret = (price_fwd - price_now) / price_now
        returns_by_phase[phase].append((ret, score))

    def _filter(items: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(r, s) for r, s in items if s >= min_score]

    bull_ok = bull_total = 0
    bear_ok = bear_total = 0
    for phase, lst in returns_by_phase.items():
        lst_f = _filter(lst)
        if not lst_f:
            continue
        if phase in BULLISH_PHASES:
            bull_total += len(lst_f)
            bull_ok += sum(1 for r, _ in lst_f if r >= threshold_up)
        elif phase in BEARISH_PHASES:
            bear_total += len(lst_f)
            bear_ok += sum(1 for r, _ in lst_f if r <= threshold_down)
    total_n = bull_total + bear_total
    total_ok = bull_ok + bear_ok
    total_accuracy = (total_ok / total_n) if total_n else 0.0
    stats = {
        "bull_ok": bull_ok,
        "bull_total": bull_total,
        "bear_ok": bear_ok,
        "bear_total": bear_total,
        "total_ok": total_ok,
        "total_n": total_n,
        "total_accuracy": total_accuracy,
    }
    return returns_by_phase, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сравнение методов определения фазы: Wyckoff, индикаторы, price action"
    )
    parser.add_argument("--symbol", default=None, help="Пара (по умолчанию из .env)")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default="60", help="Таймфрейм")
    parser.add_argument("--bars", type=int, default=20_000, help="Макс. свечей из БД")
    parser.add_argument("--lookback", type=int, default=100, help="Окно для detect_phase")
    parser.add_argument("--forward", type=int, default=20, help="Баров вперёд для доходности")
    parser.add_argument("--step", type=int, default=5, help="Шаг по времени")
    parser.add_argument("--threshold-up", type=float, default=0.005, help="Порог «рост» (0.5%%)")
    parser.add_argument("--threshold-down", type=float, default=-0.005, help="Порог «падение» (-0.5%%)")
    parser.add_argument("--min-score", type=float, default=0.0, help="Мин. score (0 = без фильтра)")
    args = parser.parse_args()

    symbol = args.symbol or config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, args.timeframe, limit=args.bars, order_asc=False)
    conn.close()

    if len(candles) < args.lookback + args.forward:
        print(
            f"Мало свечей: {len(candles)}, нужно минимум {args.lookback + args.forward}",
            file=sys.stderr,
        )
        return

    methods = [
        ("Wyckoff", detect_phase_wyckoff),
        ("Indicators", detect_phase_indicators),
        ("Structure (PA)", detect_phase_structure),
    ]

    print("=" * 70)
    print("Сравнение методов определения фазы рынка")
    print("=" * 70)
    print(f"Пара: {symbol}, ТФ: {args.timeframe}, свечей: {len(candles)}")
    print(f"Окно: lookback={args.lookback}, forward={args.forward}, шаг={args.step}")
    print(f"Пороги: рост >={args.threshold_up:.2%}, падение <={args.threshold_down:.2%}")
    if args.min_score > 0:
        print(f"Мин. score: {args.min_score}")
    print()

    results: list[tuple[str, dict[str, Any]]] = []
    for name, detect_fn in methods:
        _, stats = _run_one_method(
            candles,
            symbol=symbol,
            timeframe=args.timeframe,
            lookback=args.lookback,
            forward_bars=args.forward,
            step=args.step,
            threshold_up=args.threshold_up,
            threshold_down=args.threshold_down,
            detect_phase_fn=detect_fn,
            min_score=args.min_score,
        )
        results.append((name, stats))

    # Таблица: метод | бычьи ок/всего | медвежьи ок/всего | сводная точность
    print("-" * 70)
    print(f"{'Метод':<22} | {'Бычьи (рост)':<18} | {'Медвежьи (падение)':<22} | {'Точность':<10}")
    print("-" * 70)
    for name, st in results:
        bull_str = f"{st['bull_ok']}/{st['bull_total']}" if st["bull_total"] else "—"
        bear_str = f"{st['bear_ok']}/{st['bear_total']}" if st["bear_total"] else "—"
        acc_str = f"{st['total_accuracy']:.1%}" if st["total_n"] else "—"
        print(f"{name:<22} | {bull_str:>18} | {bear_str:>22} | {acc_str:>10}")
    print("-" * 70)

    best = max(results, key=lambda x: x[1]["total_accuracy"]) if results else None
    if best:
        print(f"\nЛучшая сводная точность: {best[0]} ({best[1]['total_accuracy']:.1%})")
    print("\nГотово.")


if __name__ == "__main__":
    main()
