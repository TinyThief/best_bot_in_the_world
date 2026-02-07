"""Проверка порядка файлов тиков и итогов последнего бэктеста."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def check_file_order():
    from src.history.storage import list_trade_files
    files = list_trade_files("BTCUSDT")
    filtered = [(p, d) for p, d in files if d >= "2025-10-06" and d <= "2026-02-07"]
    print("Файлы тиков в диапазоне 2025-10-06..2026-02-07:", len(filtered))
    print("Первые 5:")
    for p, d in filtered[:5]:
        print(" ", d, p.name)
    print("Последние 5:")
    for p, d in filtered[-5:]:
        print(" ", d, p.name)
    dates = [d for _, d in filtered]
    ok = dates == sorted(dates)
    print("Порядок дат хронологический:", ok)
    if not ok:
        for i in range(len(dates) - 1):
            if dates[i] > dates[i + 1]:
                print("  Нарушение: индекс", i, dates[i], ">", dates[i + 1])
                break

def check_db_runs():
    from src.core.database import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, symbol, date_from, date_to, started_at_sec,
               initial_balance, final_equity, total_pnl, total_commission, trades_count
        FROM sandbox_runs
        WHERE source = 'backtest'
        ORDER BY started_at_sec DESC
        LIMIT 3
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print("\nПоследние бэктест-прогоны (sandbox_runs):")
    for r in rows:
        d = dict(zip(cols, r))
        print(" ", d.get("run_id", "")[:50], "|", d.get("date_from"), "-", d.get("date_to"),
              "| init=$%.0f" % (d.get("initial_balance") or 0),
              "| final_equity=$%.2f" % (d.get("final_equity") or 0),
              "| pnl=$%.2f" % (d.get("total_pnl") or 0),
              "| comm=$%.2f" % (d.get("total_commission") or 0),
              "| trades=", d.get("trades_count"))
    conn.close()

if __name__ == "__main__":
    check_file_order()
    check_db_runs()
