"""
Утилита: поток исполненных сделок (Time & Sales) по WebSocket.

Работает до Ctrl+C или до истечения --duration. Вывод в консоль и при необходимости в файл (--log).
Запуск из корня: python bin/trades_ws_demo.py [--duration 0] [--log путь]
"""
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.core.trades_ws import TradesStream
from src.core import config


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(
        description="Поток исполненных сделок по WebSocket (до Ctrl+C или --duration сек)"
    )
    p.add_argument("--symbol", default=None, help="Пара (по умолчанию из .env)")
    p.add_argument("--duration", type=float, default=0, help="Секунд работы (0 = до Ctrl+C)")
    p.add_argument("--interval", type=float, default=2.0, help="Интервал вывода в консоль (сек)")
    p.add_argument("--log", dest="log_path", default=None, help="Путь к файлу: туда пишутся сводки (кол-во, объём, delta)")
    args = p.parse_args()

    symbol = args.symbol or config.SYMBOL
    stream = TradesStream(symbol=symbol)
    stream.start()

    log_file = None
    if args.log_path:
        try:
            log_file = open(args.log_path, "a", encoding="utf-8")
        except OSError as e:
            print(f"Не удалось открыть файл лога: {e}", file=sys.stderr)
            log_file = None

    deadline = (time.monotonic() + args.duration) if args.duration > 0 else None
    try:
        print(f"Поток сделок {symbol} (Ctrl+C — выход)", end="")
        if args.duration > 0:
            print(f", duration={args.duration} с", end="")
        if log_file:
            print(f", лог → {args.log_path}", end="")
        print("\n")

        while True:
            time.sleep(args.interval)
            if deadline is not None and time.monotonic() >= deadline:
                break
            trades = stream.get_recent_trades()
            if not trades:
                print("  (ожидание сделок…)")
                continue
            buy_vol = sum(t["size"] for t in trades if t.get("side") == "Buy")
            sell_vol = sum(t["size"] for t in trades if t.get("side") == "Sell")
            total_vol = buy_vol + sell_vol
            delta = buy_vol - sell_vol
            last_t = trades[-1]
            line = f"  сделок={len(trades)}  объём={total_vol:.4f}  buy={buy_vol:.4f}  sell={sell_vol:.4f}  delta={delta:+.4f}  последняя: {last_t['price']:.2f} {last_t['side']}"
            print(line)
            if log_file:
                ts = int(time.time())
                log_file.write(f"{ts}\t{len(trades)}\t{total_vol:.4f}\t{buy_vol:.4f}\t{sell_vol:.4f}\t{delta:+.4f}\n")
                log_file.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if log_file:
            log_file.close()
        stream.stop()
    print("\nГотово.")


if __name__ == "__main__":
    main()
