"""
Отчёт по бэктесту песочницы: сумма realized PnL и разбивка по причинам выхода.
Источник: sandbox_trades.csv или БД (sandbox_trades по run_id/году).
Запуск: python bin/sandbox_backtest_report.py [--year 2025] [--trades путь]
        python bin/sandbox_backtest_report.py --db [--run-id ID] [--year 2025]
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..app.microstructure_sandbox import _classify_exit_reason

# Индексы колонок (без заголовка в файле): ts_utc, ts_unix, action, side, price, size, notional_usd, commission_usd, realized_pnl_usd, ...
COL_TS_UTC = 0
COL_ACTION = 2
COL_COMMISSION = 7
COL_REALIZED_PNL = 8
COL_EXIT_REASON = 13


def _normalize_exit_reason(raw: str) -> str:
    """Единая классификация причины выхода (один источник правды в microstructure_sandbox)."""
    return _classify_exit_reason(raw)


def run_report(trades_path: Path, year: str) -> dict:
    """Читает sandbox_trades.csv, фильтрует close за год, считает PnL и разбивку по exit_reason."""
    total_pnl = 0.0
    total_commission = 0.0
    count = 0
    by_exit: dict[str, list[float]] = defaultdict(list)

    with open(trades_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) <= max(COL_ACTION, COL_REALIZED_PNL, COL_EXIT_REASON):
                continue
            ts_utc = row[COL_TS_UTC].strip()
            if not ts_utc.startswith(f"{year}-"):
                continue
            if row[COL_ACTION].strip().lower() != "close":
                continue
            try:
                pnl = float(row[COL_REALIZED_PNL].strip() or 0)
            except ValueError:
                pnl = 0.0
            try:
                comm = float(row[COL_COMMISSION].strip() or 0)
            except ValueError:
                comm = 0.0
            total_pnl += pnl
            total_commission += comm
            count += 1
            reason = _normalize_exit_reason(row[COL_EXIT_REASON] if len(row) > COL_EXIT_REASON else "")
            by_exit[reason].append(pnl)

    return {
        "year": year,
        "trades_path": str(trades_path),
        "closes_count": count,
        "total_realized_pnl": total_pnl,
        "total_commission": total_commission,
        "net_pnl": total_pnl - total_commission,
        "by_exit_reason": {k: (len(v), sum(v)) for k, v in sorted(by_exit.items())},
    }


def run_report_from_db(
    run_id: str | None = None,
    year: str | None = None,
) -> dict:
    """Читает сделки из БД (по run_id или по году), фильтрует close, считает PnL и разбивку по exit_reason."""
    from ..core.database import get_connection, get_sandbox_trades

    ts_from: int | None = None
    ts_to: int | None = None
    if year:
        try:
            y = int(year)
            ts_from = int(datetime(y, 1, 1).timestamp())
            ts_to = int(datetime(y, 12, 31, 23, 59, 59).timestamp())
        except ValueError:
            year = None

    conn = get_connection()
    try:
        cur = conn.cursor()
        rows = get_sandbox_trades(cur, run_id=run_id, ts_from=ts_from, ts_to=ts_to)
    finally:
        conn.close()

    total_pnl = 0.0
    total_commission = 0.0
    count = 0
    by_exit: dict[str, list[float]] = defaultdict(list)

    for r in rows:
        if (r.get("action") or "").strip().lower() != "close":
            continue
        if year and r.get("ts_utc"):
            if not str(r["ts_utc"]).startswith(f"{year}-"):
                continue
        try:
            pnl = float(r.get("realized_pnl_usd") or 0)
        except (TypeError, ValueError):
            pnl = 0.0
        try:
            comm = float(r.get("commission_usd") or 0)
        except (TypeError, ValueError):
            comm = 0.0
        total_pnl += pnl
        total_commission += comm
        count += 1
        reason = _normalize_exit_reason(str(r.get("exit_reason") or ""))
        by_exit[reason].append(pnl)

    label = f"run_id={run_id}" if run_id else f"year={year or 'all'}"
    return {
        "year": year or "",
        "run_id": run_id,
        "source": "db",
        "trades_path": label,
        "closes_count": count,
        "total_realized_pnl": total_pnl,
        "total_commission": total_commission,
        "net_pnl": total_pnl - total_commission,
        "by_exit_reason": {k: (len(v), sum(v)) for k, v in sorted(by_exit.items())},
    }


def main() -> None:
    from ..core.config import PROJECT_ROOT, LOG_DIR

    parser = argparse.ArgumentParser(description="Отчёт по бэктесту песочницы из CSV или БД")
    parser.add_argument("--db", action="store_true", help="Читать сделки из БД (sandbox_trades) вместо CSV")
    parser.add_argument("--run-id", type=str, default="", help="Фильтр по run_id (только с --db)")
    parser.add_argument("--year", default="", help="Год для фильтра (например 2025)")
    parser.add_argument("--years", type=str, default="", help="Несколько лет через запятую (2023,2024,2025) или --all для 2023–2025")
    parser.add_argument("--all", action="store_true", help="Сводка за 2023, 2024 и 2025")
    parser.add_argument("--trades", type=Path, default=None, help="Путь к sandbox_trades.csv (без --db)")
    args = parser.parse_args()

    if args.db:
        run_id = args.run_id.strip() or None
        year = args.year.strip() or None
        if args.all or args.years.strip():
            years_str = args.years.strip() or "2023,2024,2025"
            years = [y.strip() for y in years_str.split(",") if y.strip()]
            if not years:
                years = ["2023", "2024", "2025"]
            results = [run_report_from_db(year=y) for y in years]
            print("Отчёт по бэктесту песочницы (БД, сводка по годам)")
            print("-" * 60)
            total_closes = sum(r["closes_count"] for r in results)
            total_pnl = sum(r["total_realized_pnl"] for r in results)
            total_comm = sum(r["total_commission"] for r in results)
            for r in results:
                print(f"{r['year']}: закрытий={r['closes_count']}, гросс=${r['total_realized_pnl']:.2f}, комиссия=${r['total_commission']:.2f}, нетто=${r['net_pnl']:.2f}")
            print("-" * 60)
            print(f"Итого: закрытий={total_closes}, гросс=${total_pnl:.2f}, комиссия=${total_comm:.2f}, нетто=${total_pnl - total_comm:.2f}")
        else:
            if run_id:
                result = run_report_from_db(run_id=run_id)
            else:
                result = run_report_from_db(year=year or "2025")
            print(f"Отчёт по бэктесту песочницы (БД) {result['trades_path']}")
            print(f"Закрытий (close): {result['closes_count']}")
            print(f"Реализованный PnL: ${result['total_realized_pnl']:.2f}")
            print(f"Комиссия: ${result['total_commission']:.2f}")
            print(f"Чистый PnL: ${result['net_pnl']:.2f}")
            print("\nПо причинам выхода:")
            for reason, (cnt, pnl) in result["by_exit_reason"].items():
                print(f"  {reason}: сделок={cnt}, PnL=${pnl:.2f}")
        return

    trades_path = args.trades or LOG_DIR / "sandbox_trades.csv"
    if not trades_path.is_absolute():
        trades_path = PROJECT_ROOT / trades_path
    if not trades_path.exists():
        print(f"Файл не найден: {trades_path}")
        return

    if args.all or args.years.strip():
        years_str = args.years.strip() or "2023,2024,2025"
        years = [y.strip() for y in years_str.split(",") if y.strip()]
        if not years:
            years = ["2023", "2024", "2025"]
        results = [run_report(trades_path, y) for y in years]
        print("Отчёт по бэктесту песочницы (сводка по годам)")
        print(f"Файл: {trades_path}")
        print("-" * 60)
        total_closes = 0
        total_pnl = 0.0
        total_comm = 0.0
        for r in results:
            total_closes += r["closes_count"]
            total_pnl += r["total_realized_pnl"]
            total_comm += r["total_commission"]
            print(f"{r['year']}: закрытий={r['closes_count']}, гросс=${r['total_realized_pnl']:.2f}, комиссия=${r['total_commission']:.2f}, нетто=${r['net_pnl']:.2f}")
        print("-" * 60)
        print(f"Итого: закрытий={total_closes}, гросс=${total_pnl:.2f}, комиссия=${total_comm:.2f}, нетто=${total_pnl - total_comm:.2f}")
        return

    year = args.year.strip() or "2025"
    result = run_report(trades_path, year)

    print(f"Отчёт по бэктесту песочницы за {result['year']}")
    print(f"Файл: {result['trades_path']}")
    print(f"Закрытий (close): {result['closes_count']}")
    print(f"Реализованный PnL: ${result['total_realized_pnl']:.2f}")
    print(f"Комиссия: ${result['total_commission']:.2f}")
    print(f"Чистый PnL (после комиссии): ${result['net_pnl']:.2f}")
    print("\nПо причинам выхода:")
    for reason, (cnt, pnl) in result["by_exit_reason"].items():
        print(f"  {reason}: сделок={cnt}, PnL=${pnl:.2f}")


if __name__ == "__main__":
    main()
