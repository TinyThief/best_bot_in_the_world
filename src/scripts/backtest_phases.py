"""
Бэктест точности определения фаз рынка.

Берёт исторические свечи из БД, в каждой точке прогоняет detect_phase по прошлым барам,
смотрит форвард-доходность и считает точность по направлению (бычьи/медвежьи).
Капитуляция трактуется как «ожидаем отскок» (бычья).

Опция --tune: перебор порогов (vol_spike, drop_threshold, range_position) и вывод лучшей комбинации.

Запуск: python backtest_phases.py [--tf 60] [--bars 20000]; с подбором: python backtest_phases.py --tune --tf 60 --bars 10000
"""
from __future__ import annotations

import argparse
import itertools
import sys
from collections import defaultdict
from typing import Any

from ..core import config
from ..core.database import get_connection, get_candles
from ..analysis.market_phases import BEARISH_PHASES, BULLISH_PHASES, PHASE_NAMES_RU, PHASES, detect_phase


def _run_one(
    candles: list[dict[str, Any]],
    symbol: str,
    timeframe: str,
    lookback: int,
    forward_bars: int,
    step: int,
    threshold_up: float,
    threshold_down: float,
    phase_overrides: dict[str, Any] | None = None,
    min_score: float = 0.0,
) -> tuple[dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """
    Один прогон бэктеста. phase_overrides передаются в detect_phase.
    min_score: включать в агрегацию только оценки с score >= min_score (0 = без фильтра).
    returns_by_phase: phase -> [(ret, score), ...]
    """
    returns_by_phase: dict[str, list[tuple[float, float]]] = defaultdict(list)
    n = len(candles)
    kwargs = {"lookback": lookback, "timeframe": timeframe}
    if phase_overrides:
        kwargs.update(phase_overrides)

    for i in range(lookback, n - forward_bars + 1, step):
        window = candles[i - lookback : i]
        res = detect_phase(window, **kwargs)
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
        "symbol": symbol,
        "timeframe": timeframe,
        "min_score": min_score,
    }
    return returns_by_phase, stats


def run(
    symbol: str | None = None,
    timeframe: str = "60",
    max_bars: int = 50_000,
    lookback: int = 100,
    forward_bars: int = 20,
    step: int = 5,
    threshold_up: float = 0.005,
    threshold_down: float = -0.005,
    phase_overrides: dict[str, Any] | None = None,
    min_score: float = 0.0,
) -> None:
    symbol = symbol or config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()

    if len(candles) < lookback + forward_bars:
        print(f"Мало свечей: {len(candles)}, нужно минимум {lookback + forward_bars}", file=sys.stderr)
        return

    returns_by_phase, stats = _run_one(
        candles, symbol, timeframe, lookback, forward_bars, step,
        threshold_up, threshold_down, phase_overrides, min_score=min_score,
    )

    bull_ok, bull_total = stats["bull_ok"], stats["bull_total"]
    bear_ok, bear_total = stats["bear_ok"], stats["bear_total"]
    min_score_used = stats.get("min_score", 0.0)

    def _filter(lst: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(r, s) for r, s in lst if s >= min_score_used]

    # Отчёт
    print("=" * 60)
    print("Бэктест фаз рынка | detect_phase vs форвард-доходность")
    print("=" * 60)
    print(f"Пара: {symbol}, ТФ: {timeframe}")
    print(f"Окно: lookback={lookback}, forward={forward_bars} бар, шаг={step}")
    print(f"Пороги «рост»/«падение»: {threshold_up:.2%} / {threshold_down:.2%}")
    if min_score_used > 0:
        print(f"Мин. score: {min_score_used} (учтены только оценки с score >= {min_score_used})")
    total_all = sum(len(v) for v in returns_by_phase.values())
    total_filtered = sum(len(_filter(v)) for v in returns_by_phase.values())
    print(f"Всего оценок: {total_filtered}" + (f" (из {total_all})" if min_score_used > 0 else ""))
    print()

    for phase in sorted(returns_by_phase.keys(), key=lambda p: (p not in BULLISH_PHASES and p not in BEARISH_PHASES, p)):
        lst = _filter(returns_by_phase[phase])
        if not lst:
            continue
        rets = [r for r, _ in lst]
        mean_ret = sum(rets) / len(rets)
        pct_up = sum(1 for r in rets if r >= threshold_up) / len(rets) * 100
        pct_down = sum(1 for r in rets if r <= threshold_down) / len(rets) * 100
        pct_positive = sum(1 for r in rets if r > 0) / len(rets) * 100
        name_ru = PHASE_NAMES_RU.get(phase, phase)
        expectation = ""
        if phase == "capitulation":
            expectation = " (ожидаем отскок)"
        elif phase in BULLISH_PHASES:
            expectation = " (ожидаем рост)"
        elif phase in BEARISH_PHASES:
            expectation = " (ожидаем падение)"

        print(f"  {phase:14} ({name_ru}){expectation}")
        print(f"    наблюдений: {len(lst):6}  |  средняя дох-ть: {mean_ret:+.2%}  |  >0: {pct_positive:.1f}%  |  >{threshold_up:.2%}: {pct_up:.1f}%  |  <{threshold_down:.2%}: {pct_down:.1f}%")
        print()

    # Сводная «точность по направлению»
    print("--- Точность по направлению ---")
    if bull_total:
        print(f"  Бычьи (markup, recovery, capitulation=отскок): после них рост >={threshold_up:.2%} в {bull_ok}/{bull_total} = {bull_ok/bull_total*100:.1f}% случаев")
    if bear_total:
        print(f"  Медвежьи (markdown, distribution): после них падение <={threshold_down:.2%} в {bear_ok}/{bear_total} = {bear_ok/bear_total*100:.1f}% случаев")
    if bull_total or bear_total:
        total_ok = bull_ok + bear_ok
        total_n = bull_total + bear_total
        print(f"  Сводно (бычьи+медвежьи): {total_ok}/{total_n} = {total_ok/total_n*100:.1f}% «попадений» по направлению")
    print()
    print("Готово.")


def _tune(
    symbol: str,
    timeframe: str,
    max_bars: int,
    lookback: int,
    forward_bars: int,
    step: int,
    threshold_up: float,
    threshold_down: float,
) -> None:
    """Перебор порогов и вывод лучшей комбинации."""
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()
    if len(candles) < lookback + forward_bars:
        print(f"Мало свечей: {len(candles)}", file=sys.stderr)
        return

    grid = {
        "vol_spike": [1.5, 1.8, 2.0, 2.2],
        "drop_threshold": [-0.07, -0.05, -0.04, -0.03],
        "range_position_low": [0.30, 0.35],
        "range_position_high": [0.65, 0.70],
    }
    keys = list(grid.keys())
    values = list(grid.values())
    best_acc = -1.0
    best_combo: dict[str, Any] = {}
    best_stats: dict[str, Any] = {}

    for combo in itertools.product(*values):
        overrides = dict(zip(keys, combo))
        _, stats = _run_one(
            candles, symbol, timeframe, lookback, forward_bars, step,
            threshold_up, threshold_down, overrides,
        )
        acc = stats["total_accuracy"]
        if acc > best_acc:
            best_acc = acc
            best_combo = overrides
            best_stats = stats

    print("--- Подбор порогов (--tune) ---")
    print(f"Пара: {symbol}, ТФ: {timeframe}, баров: {len(candles)}, оценок: {best_stats.get('total_n', 0)}")
    print(f"Лучшая точность по направлению: {best_acc:.1%}")
    print("Параметры:")
    for k, v in best_combo.items():
        print(f"  {k}: {v}")
    print()
    print("Рекомендуется добавить в PHASE_PROFILES в market_phases.py для соответствующего ТФ.")
    print("Полный отчёт с этими порогами: python backtest_phases.py --tf {} --vol-spike {} --drop-threshold {} --range-low {} --range-high {} --bars {} --step {}"
          .format(timeframe, best_combo.get("vol_spike"), best_combo.get("drop_threshold"),
                  best_combo.get("range_position_low"), best_combo.get("range_position_high"), max_bars, step))


def main() -> None:
    parser = argparse.ArgumentParser(description="Бэктест точности фаз рынка по данным из БД")
    parser.add_argument("--symbol", default=None, help="Пара (по умолчанию из .env)")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default="60", help="Таймфрейм (по умолчанию 60)")
    parser.add_argument("--bars", type=int, default=50_000, help="Макс. свечей из БД (по умолчанию 50000)")
    parser.add_argument("--lookback", type=int, default=100, help="Окно для detect_phase (по умолчанию 100)")
    parser.add_argument("--forward", type=int, default=20, help="Баров вперёд для доходности (по умолчанию 20)")
    parser.add_argument("--step", type=int, default=5, help="Шаг по времени (каждые step баров) для ускорения")
    parser.add_argument("--threshold-up", type=float, default=0.005, help="Порог «рост» (доля, по умолчанию 0.5%%)")
    parser.add_argument("--threshold-down", type=float, default=-0.005, help="Порог «падение» (доля, по умолчанию -0.5%%)")
    parser.add_argument("--min-score", type=float, default=0.0, help="Учитывать только оценки с score >= N (0 = без фильтра)")
    parser.add_argument("--tune", action="store_true", help="Подбор порогов vol_spike, drop_threshold, range_position")
    parser.add_argument("--vol-spike", type=float, default=None, help="Переопределить vol_spike для detect_phase")
    parser.add_argument("--drop-threshold", type=float, default=None, help="Переопределить drop_threshold")
    parser.add_argument("--range-low", type=float, default=None, dest="range_position_low", help="Переопределить range_position_low")
    parser.add_argument("--range-high", type=float, default=None, dest="range_position_high", help="Переопределить range_position_high")
    args = parser.parse_args()

    phase_overrides = {}
    if args.vol_spike is not None:
        phase_overrides["vol_spike"] = args.vol_spike
    if args.drop_threshold is not None:
        phase_overrides["drop_threshold"] = args.drop_threshold
    if args.range_position_low is not None:
        phase_overrides["range_position_low"] = args.range_position_low
    if args.range_position_high is not None:
        phase_overrides["range_position_high"] = args.range_position_high

    symbol = args.symbol or config.SYMBOL
    if args.tune:
        _tune(
            symbol=symbol,
            timeframe=args.timeframe,
            max_bars=args.bars,
            lookback=args.lookback,
            forward_bars=args.forward,
            step=args.step,
            threshold_up=args.threshold_up,
            threshold_down=args.threshold_down,
        )
        return

    run(
        symbol=symbol,
        timeframe=args.timeframe,
        max_bars=args.bars,
        lookback=args.lookback,
        forward_bars=args.forward,
        step=args.step,
        threshold_up=args.threshold_up,
        threshold_down=args.threshold_down,
        phase_overrides=phase_overrides if phase_overrides else None,
        min_score=args.min_score,
    )


if __name__ == "__main__":
    main()
