"""
Бэктест точности определения фаз рынка.

Берёт исторические свечи из БД, в каждой точке прогоняет detect_phase по прошлым барам,
смотрит форвард-доходность и считает точность по направлению (бычьи/медвежьи).
Капитуляция трактуется как «ожидаем отскок» (бычья).

Опция --tune: перебор порогов (vol_spike, drop_threshold, range_position) и min_score; вывод лучшей комбинации.
Опция --sweep-min-score: таблица точности по разным --min-score (0, 0.5, 0.55, 0.6, 0.65, 0.7).
Опции --train-ratio / --oos-bars: разделение на train (калибровка) и out-of-sample (OOS). При --tune подбор только по train; итоговая метрика по OOS — ближе к форварду. См. docs/BACKTEST_OOS.md.

Запуск: python backtest_phases.py [--tf 60] [--bars 20000]; с подбором: python backtest_phases.py --tune --tf 60 --bars 10000; с OOS: python backtest_phases.py --train-ratio 0.7 --tf 60
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


def run_for_chart(
    symbol: str | None = None,
    timeframe: str = "60",
    max_bars: int | None = None,
    lookback: int = 100,
    forward_bars: int = 20,
    step: int = 5,
    threshold_up: float = 0.005,
    threshold_down: float = -0.005,
    phase_overrides: dict[str, Any] | None = None,
    min_score: float = 0.0,
) -> dict[str, Any] | None:
    """
    Запуск бэктеста фаз и возврат данных для визуализации (график в Telegram и т.п.).

    max_bars: если None — используются все свечи по паре и таймфрейму из БД (весь период).
    Возвращает dict: stats (total_accuracy, bull_ok, bull_total, bear_ok, bear_total, symbol, timeframe),
    phase_summary (список по фазам: phase, name_ru, count, mean_ret, pct_positive, pct_up, pct_down).
    При ошибке или недостатке данных возвращает None.
    """
    symbol = symbol or config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()

    if len(candles) < lookback + forward_bars:
        return None

    returns_by_phase, stats = _run_one(
        candles, symbol, timeframe, lookback, forward_bars, step,
        threshold_up, threshold_down, phase_overrides, min_score=min_score,
    )
    min_score_used = stats.get("min_score", 0.0)

    def _filter(lst: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(r, s) for r, s in lst if s >= min_score_used]

    phase_summary: list[dict[str, Any]] = []
    for phase in sorted(returns_by_phase.keys(), key=lambda p: (p not in BULLISH_PHASES and p not in BEARISH_PHASES, p)):
        lst = _filter(returns_by_phase[phase])
        if not lst:
            continue
        rets = [r for r, _ in lst]
        mean_ret = sum(rets) / len(rets)
        pct_up = sum(1 for r in rets if r >= threshold_up) / len(rets) * 100
        pct_down = sum(1 for r in rets if r <= threshold_down) / len(rets) * 100
        pct_positive = sum(1 for r in rets if r > 0) / len(rets) * 100
        phase_summary.append({
            "phase": phase,
            "name_ru": PHASE_NAMES_RU.get(phase, phase),
            "count": len(lst),
            "mean_ret": mean_ret,
            "pct_positive": pct_positive,
            "pct_up": pct_up,
            "pct_down": pct_down,
        })

    return {
        "stats": stats,
        "phase_summary": phase_summary,
        "threshold_up": threshold_up,
        "threshold_down": threshold_down,
        "bars_used": len(candles),
    }


def _split_candles(
    candles: list[dict[str, Any]],
    lookback: int,
    forward_bars: int,
    train_ratio: float | None = None,
    oos_bars: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """
    Делит свечи по времени: train = более старая часть, test = более новая (OOS).
    Свечи в порядке order_asc=False: candles[0]=новейшая, candles[-1]=самая старая.
    train_ratio: доля данных для train (0.7 = 70% старых = train, 30% новых = OOS).
    oos_bars: ровно столько последних баров = OOS.
    Возвращает (train_candles, test_candles) или None, если сплит невозможен.
    """
    n = len(candles)
    min_len = lookback + forward_bars
    if n < min_len * 2:
        return None
    if oos_bars is not None:
        if oos_bars < min_len or n - oos_bars < min_len:
            return None
        split_idx = oos_bars
    elif train_ratio is not None and 0 < train_ratio < 1:
        split_idx = int(n * (1 - train_ratio))
        if split_idx < min_len or n - split_idx < min_len:
            return None
    else:
        return None
    train = candles[split_idx:]
    test = candles[:split_idx]
    return (train, test)


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
    train_ratio: float | None = None,
    oos_bars: int | None = None,
) -> None:
    symbol = symbol or config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()

    if len(candles) < lookback + forward_bars:
        print(f"Мало свечей: {len(candles)}, нужно минимум {lookback + forward_bars}", file=sys.stderr)
        return

    split = _split_candles(candles, lookback, forward_bars, train_ratio, oos_bars)
    if split is not None:
        train_candles, test_candles = split
        _, stats_train = _run_one(
            train_candles, symbol, timeframe, lookback, forward_bars, step,
            threshold_up, threshold_down, phase_overrides, min_score=min_score,
        )
        _, stats_test = _run_one(
            test_candles, symbol, timeframe, lookback, forward_bars, step,
            threshold_up, threshold_down, phase_overrides, min_score=min_score,
        )
        print("=" * 60)
        print("Бэктест фаз рынка | train / out-of-sample (OOS)")
        print("=" * 60)
        print(f"Пара: {symbol}, ТФ: {timeframe}")
        print(f"Train: {len(train_candles)} бар (старшая часть)  |  OOS: {len(test_candles)} бар (новейшая часть)")
        print(f"Окно: lookback={lookback}, forward={forward_bars}, шаг={step}")
        print()
        print("In-sample (train):  точность по направлению = {:.1f}%  (оценок: {})".format(
            stats_train["total_accuracy"] * 100, stats_train.get("total_n", 0)))
        print("Out-of-sample (OOS): точность по направлению = {:.1f}%  (оценок: {})  ← ориентируйся на это".format(
            stats_test["total_accuracy"] * 100, stats_test.get("total_n", 0)))
        print()
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


# Значения min_score для перебора при --tune и --sweep-min-score
MIN_SCORE_SWEEP = (0.0, 0.5, 0.55, 0.6, 0.65, 0.7)


def _tune(
    symbol: str,
    timeframe: str,
    max_bars: int,
    lookback: int,
    forward_bars: int,
    step: int,
    threshold_up: float,
    threshold_down: float,
    train_ratio: float | None = None,
    oos_bars: int | None = None,
) -> None:
    """Перебор порогов и min_score по train; при сплите — итоговая точность по OOS."""
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()
    if len(candles) < lookback + forward_bars:
        print(f"Мало свечей: {len(candles)}", file=sys.stderr)
        return

    split = _split_candles(candles, lookback, forward_bars, train_ratio, oos_bars)
    train_candles = candles
    test_candles: list[dict[str, Any]] | None = None
    if split is not None:
        train_candles, test_candles = split
        print("--- Подбор только по train (OOS не используется при выборе) ---")
        print(f"Train: {len(train_candles)} бар, OOS: {len(test_candles)} бар")

    # Сетка порогов: 2×2×2×2 = 16 комбинаций × 7 min_score ≈ 112 прогонов
    grid = {
        "vol_spike": [1.8, 2.0],
        "drop_threshold": [-0.05, -0.04],
        "range_position_low": [0.30, 0.35],
        "range_position_high": [0.65, 0.70],
    }
    keys = list(grid.keys())
    values = list(grid.values())
    best_acc = -1.0
    best_combo: dict[str, Any] = {}
    best_min_score = 0.0
    best_stats: dict[str, Any] = {}

    for combo in itertools.product(*values):
        overrides = dict(zip(keys, combo))
        for min_score in MIN_SCORE_SWEEP:
            _, stats = _run_one(
                train_candles, symbol, timeframe, lookback, forward_bars, step,
                threshold_up, threshold_down, overrides, min_score=min_score,
            )
            acc = stats["total_accuracy"]
            total_n = stats.get("total_n", 0)
            if total_n >= 50 and acc > best_acc:
                best_acc = acc
                best_combo = overrides.copy()
                best_min_score = min_score
                best_stats = stats

    print("--- Подбор порогов и min_score (--tune) ---")
    print(f"Пара: {symbol}, ТФ: {timeframe}")
    print(f"In-sample (train): лучшая точность = {best_acc:.1%} (оценок: {best_stats.get('total_n', 0)})")
    if test_candles is not None:
        _, stats_oos = _run_one(
            test_candles, symbol, timeframe, lookback, forward_bars, step,
            threshold_up, threshold_down, best_combo, min_score=best_min_score,
        )
        print(f"Out-of-sample (OOS): точность с лучшей комбинацией = {stats_oos['total_accuracy']:.1%} (оценок: {stats_oos.get('total_n', 0)})  ← ориентируйся на это")
    print("Пороги (PHASE_PROFILES):")
    for k, v in best_combo.items():
        print(f"  {k}: {v}")
    print(f"  min_score (фильтр): {best_min_score}")
    print()
    print("Рекомендации:")
    print("  1. Добавь пороги в PHASE_PROFILES в market_phases.py для соответствующего ТФ.")
    print("  2. В .env задай PHASE_SCORE_MIN={} (или оставь текущее).".format(best_min_score))
    print("Полный отчёт: python bin/backtest_phases.py --tf {} --vol-spike {} --drop-threshold {} --range-low {} --range-high {} --min-score {} --bars {} --step {}"
          .format(
              timeframe,
              best_combo.get("vol_spike"),
              best_combo.get("drop_threshold"),
              best_combo.get("range_position_low"),
              best_combo.get("range_position_high"),
              best_min_score,
              max_bars,
              step,
          ))


def _sweep_min_score(
    symbol: str,
    timeframe: str,
    max_bars: int,
    lookback: int,
    forward_bars: int,
    step: int,
    threshold_up: float,
    threshold_down: float,
    phase_overrides: dict[str, Any] | None = None,
    train_ratio: float | None = None,
    oos_bars: int | None = None,
) -> None:
    """Таблица точности по min_score; при сплите — колонки train и OOS."""
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()
    if len(candles) < lookback + forward_bars:
        print(f"Мало свечей: {len(candles)}", file=sys.stderr)
        return

    split = _split_candles(candles, lookback, forward_bars, train_ratio, oos_bars)
    train_candles = candles
    test_candles: list[dict[str, Any]] | None = None
    if split is not None:
        train_candles, test_candles = split

    rows: list[tuple[float, float, int, float, int]] = []
    for min_score in MIN_SCORE_SWEEP:
        _, stats = _run_one(
            train_candles, symbol, timeframe, lookback, forward_bars, step,
            threshold_up, threshold_down, phase_overrides, min_score=min_score,
        )
        acc = stats["total_accuracy"]
        total_n = stats["total_n"]
        if test_candles is not None:
            _, stats_oos = _run_one(
                test_candles, symbol, timeframe, lookback, forward_bars, step,
                threshold_up, threshold_down, phase_overrides, min_score=min_score,
            )
            rows.append((min_score, acc, total_n, stats_oos["total_accuracy"], stats_oos["total_n"]))
        else:
            rows.append((min_score, acc, total_n, -1.0, 0))

    print("--- Таблица точности по min_score (--sweep-min-score) ---")
    print(f"Пара: {symbol}, ТФ: {timeframe}, баров: {len(candles)}, lookback={lookback}, forward={forward_bars}, step={step}")
    if test_candles is not None:
        print(f"Train: {len(train_candles)} бар, OOS: {len(test_candles)} бар")
    print()
    if test_candles is not None:
        print(f"  {'min_score':>8}  {'train acc':>10}  {'train n':>8}  {'OOS acc':>10}  {'OOS n':>8}")
        print("  " + "-" * 52)
        for min_score, acc, total_n, acc_oos, n_oos in rows:
            oos_str = f"{acc_oos:.1%}" if acc_oos >= 0 else "—"
            print(f"  {min_score:>8.2f}  {acc:>9.1%}  {total_n:>8}  {oos_str:>10}  {n_oos:>8}")
        best_oos = max(rows, key=lambda r: (r[3], r[4]))
        print()
        print(f"Лучшая OOS точность: {best_oos[3]:.1%} при min_score={best_oos[0]} (ориентируйся на OOS).")
    else:
        print(f"  {'min_score':>8}  {'точность':>8}  {'оценок':>8}")
        print("  " + "-" * 28)
        for min_score, acc, total_n, _, _ in rows:
            print(f"  {min_score:>8.2f}  {acc:>7.1%}  {total_n:>8}")
        best_row = max(rows, key=lambda r: (r[1], r[2]))
        print()
        print(f"Лучшая точность: {best_row[1]:.1%} при min_score={best_row[0]}, оценок={best_row[2]}")
    print("Рекомендация: задай PHASE_SCORE_MIN в .env или используй --min-score в бэктесте.")


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
    parser.add_argument("--tune", action="store_true", help="Подбор порогов и min_score; вывод лучшей комбинации")
    parser.add_argument("--sweep-min-score", action="store_true", help="Таблица точности по min_score (0, 0.5, 0.55, 0.6, 0.65, 0.7)")
    parser.add_argument("--vol-spike", type=float, default=None, help="Переопределить vol_spike для detect_phase")
    parser.add_argument("--drop-threshold", type=float, default=None, help="Переопределить drop_threshold")
    parser.add_argument("--range-low", type=float, default=None, dest="range_position_low", help="Переопределить range_position_low")
    parser.add_argument("--range-high", type=float, default=None, dest="range_position_high", help="Переопределить range_position_high")
    parser.add_argument("--train-ratio", type=float, default=None, help="Доля данных для train (0.7 = 70%% старых), остальное = OOS. См. docs/BACKTEST_OOS.md")
    parser.add_argument("--oos-bars", type=int, default=None, help="Ровно столько последних баров = out-of-sample (остальное = train)")
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
            train_ratio=getattr(args, "train_ratio", None),
            oos_bars=getattr(args, "oos_bars", None),
        )
        return

    if args.sweep_min_score:
        _sweep_min_score(
            symbol=symbol,
            timeframe=args.timeframe,
            max_bars=args.bars,
            lookback=args.lookback,
            forward_bars=args.forward,
            step=args.step,
            threshold_up=args.threshold_up,
            threshold_down=args.threshold_down,
            phase_overrides=phase_overrides if phase_overrides else None,
            train_ratio=getattr(args, "train_ratio", None),
            oos_bars=getattr(args, "oos_bars", None),
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
        train_ratio=getattr(args, "train_ratio", None),
        oos_bars=getattr(args, "oos_bars", None),
    )


if __name__ == "__main__":
    main()
