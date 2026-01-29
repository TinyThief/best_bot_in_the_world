"""
Бэктест точности определения тренда.

Берёт исторические свечи из БД, в каждой точке прогоняет detect_trend по прошлым барам,
смотрит форвард-доходность и считает точность по направлению (up → рост, down → падение).
flat не считается «попаданием» по направлению.

Опция --min-strength: учитывать только оценки с strength >= N.
Опция --tune: перебор порогов TREND_STRENGTH_MIN, TREND_UNCLEAR_THRESHOLD (через переопределение в config).

Запуск: python backtest_trend.py [--tf 60] [--bars 20000]; с фильтром: python backtest_trend.py --min-strength 0.4
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Any

from ..core import config
from ..core.database import get_connection, get_candles
from ..analysis.market_trend import TREND_NAMES_RU, detect_trend


def _run_one(
    candles: list[dict[str, Any]],
    symbol: str,
    timeframe: str,
    lookback: int,
    forward_bars: int,
    step: int,
    threshold_up: float,
    threshold_down: float,
    min_strength: float = 0.0,
) -> tuple[dict[str, list[tuple[float, float, float]]], dict[str, Any]]:
    """
    Один прогон бэктеста тренда.
    returns_by_direction: direction -> [(ret, strength, confidence), ...]
    """
    returns_by_direction: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    n = len(candles)

    for i in range(lookback, n - forward_bars + 1, step):
        window = candles[i - lookback : i]
        res = detect_trend(window, timeframe=timeframe)
        direction = res["direction"]
        strength = res.get("strength", 0.0)
        confidence = res.get("trend_confidence", 0.0)
        price_now = candles[i]["close"]
        price_fwd = candles[i + forward_bars - 1]["close"]
        if price_now <= 0:
            continue
        ret = (price_fwd - price_now) / price_now
        returns_by_direction[direction].append((ret, strength, confidence))

    up_list = [(r, s, c) for r, s, c in returns_by_direction["up"] if s >= min_strength]
    down_list = [(r, s, c) for r, s, c in returns_by_direction["down"] if s >= min_strength]
    flat_list = returns_by_direction["flat"]

    up_ok = sum(1 for r, _, _ in up_list if r >= threshold_up)
    down_ok = sum(1 for r, _, _ in down_list if r <= threshold_down)
    up_total = len(up_list)
    down_total = len(down_list)
    total_n = up_total + down_total
    total_ok = up_ok + down_ok
    total_accuracy = (total_ok / total_n) if total_n else 0.0

    stats = {
        "up_ok": up_ok,
        "up_total": up_total,
        "down_ok": down_ok,
        "down_total": down_total,
        "flat_count": len(flat_list),
        "total_ok": total_ok,
        "total_n": total_n,
        "total_accuracy": total_accuracy,
        "symbol": symbol,
        "timeframe": timeframe,
        "min_strength": min_strength,
    }
    return returns_by_direction, stats


def run(
    symbol: str | None = None,
    timeframe: str = "60",
    max_bars: int = 50_000,
    lookback: int = 100,
    forward_bars: int = 20,
    step: int = 5,
    threshold_up: float = 0.005,
    threshold_down: float = -0.005,
    min_strength: float = 0.0,
) -> None:
    symbol = symbol or config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    candles = get_candles(cur, symbol, timeframe, limit=max_bars, order_asc=False)
    conn.close()

    if len(candles) < lookback + forward_bars:
        print(f"Мало свечей: {len(candles)}, нужно минимум {lookback + forward_bars}", file=sys.stderr)
        return

    returns_by_direction, stats = _run_one(
        candles, symbol, timeframe, lookback, forward_bars, step,
        threshold_up, threshold_down, min_strength=min_strength,
    )

    up_ok = stats["up_ok"]
    up_total = stats["up_total"]
    down_ok = stats["down_ok"]
    down_total = stats["down_total"]
    flat_count = stats["flat_count"]
    total_ok = stats["total_ok"]
    total_n = stats["total_n"]
    total_accuracy = stats["total_accuracy"]

    print("=" * 60)
    print("Бэктест тренда | detect_trend vs форвард-доходность")
    print("=" * 60)
    print(f"Пара: {symbol}, ТФ: {timeframe}")
    print(f"Окно: lookback={lookback}, forward={forward_bars} бар, шаг={step}")
    print(f"Пороги «рост»/«падение»: {threshold_up:.2%} / {threshold_down:.2%}")
    if min_strength > 0:
        print(f"Мин. strength: {min_strength} (учтены только оценки с strength >= {min_strength})")
    total_all = sum(len(v) for v in returns_by_direction.values())
    print(f"Всего оценок up: {up_total}, down: {down_total}, flat: {flat_count}" + (f" (из {total_all})" if min_strength > 0 else ""))
    print()

    for direction in ("up", "down", "flat"):
        lst = returns_by_direction[direction]
        if min_strength > 0 and direction != "flat":
            lst = [(r, s, c) for r, s, c in lst if s >= min_strength]
        if not lst:
            continue
        rets = [r for r, _, _ in lst]
        mean_ret = sum(rets) / len(rets)
        pct_up = sum(1 for r in rets if r >= threshold_up) / len(rets) * 100
        pct_down = sum(1 for r in rets if r <= threshold_down) / len(rets) * 100
        pct_positive = sum(1 for r in rets if r > 0) / len(rets) * 100
        name_ru = TREND_NAMES_RU.get(direction, direction)
        print(f"  {direction:6} ({name_ru})")
        print(f"    наблюдений: {len(lst):6}  |  средняя дох-ть: {mean_ret:+.2%}  |  >0: {pct_positive:.1f}%  |  >{threshold_up:.2%}: {pct_up:.1f}%  |  <{threshold_down:.2%}: {pct_down:.1f}%")
        print()

    print("--- Точность по направлению ---")
    if up_total:
        print(f"  Up (тренд вверх): после них рост >={threshold_up:.2%} в {up_ok}/{up_total} = {up_ok/up_total*100:.1f}% случаев")
    if down_total:
        print(f"  Down (тренд вниз): после них падение <={threshold_down:.2%} в {down_ok}/{down_total} = {down_ok/down_total*100:.1f}% случаев")
    if total_n:
        print(f"  Сводно (up+down): {total_ok}/{total_n} = {total_accuracy*100:.1f}% «попадений» по направлению")
    print()
    print("Готово.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Бэктест точности тренда по данным из БД")
    parser.add_argument("--symbol", default=None, help="Пара (по умолчанию из .env)")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default="60", help="Таймфрейм (по умолчанию 60)")
    parser.add_argument("--bars", type=int, default=50_000, help="Макс. свечей из БД (по умолчанию 50000)")
    parser.add_argument("--lookback", type=int, default=100, help="Окно для detect_trend (по умолчанию 100)")
    parser.add_argument("--forward", type=int, default=20, help="Баров вперёд для доходности (по умолчанию 20)")
    parser.add_argument("--step", type=int, default=5, help="Шаг по времени для ускорения")
    parser.add_argument("--threshold-up", type=float, default=0.005, help="Порог «рост» (доля, по умолчанию 0.5%%)")
    parser.add_argument("--threshold-down", type=float, default=-0.005, help="Порог «падение» (доля, по умолчанию -0.5%%)")
    parser.add_argument("--min-strength", type=float, default=0.0, help="Учитывать только оценки с strength >= N (0 = без фильтра)")
    args = parser.parse_args()

    run(
        symbol=args.symbol or config.SYMBOL,
        timeframe=args.timeframe,
        max_bars=args.bars,
        lookback=args.lookback,
        forward_bars=args.forward,
        step=args.step,
        threshold_up=args.threshold_up,
        threshold_down=args.threshold_down,
        min_strength=args.min_strength,
    )


if __name__ == "__main__":
    main()
