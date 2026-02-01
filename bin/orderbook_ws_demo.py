"""
Утилита: стакан по WebSocket в реальном времени.

Работает до Ctrl+C или до истечения --duration. Вывод в консоль и при необходимости в файл (--log).
Запуск из корня: python bin/orderbook_ws_demo.py [--depth 50] [--duration 0] [--log путь]
"""
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from src.core.orderbook_ws import OrderbookStream
from src.core import config


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(
        description="Стакан по WebSocket в реальном времени (до Ctrl+C или --duration сек)"
    )
    p.add_argument("--symbol", default=None, help="Пара (по умолчанию из .env)")
    p.add_argument("--depth", type=int, default=50, help="Глубина стакана: 1, 50, 200, 1000 (по умолчанию 50)")
    p.add_argument("--duration", type=float, default=0, help="Секунд работы (0 = до Ctrl+C)")
    p.add_argument("--interval", type=float, default=1.0, help="Интервал вывода в консоль (сек, по умолчанию 1)")
    p.add_argument("--log", dest="log_path", default=None, help="Путь к файлу: туда пишутся строки bid/ask/spread/u")
    args = p.parse_args()

    symbol = args.symbol or config.SYMBOL
    stream = OrderbookStream(symbol=symbol, depth=args.depth)
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
        print(f"Стакан {symbol} depth={args.depth} (Ctrl+C — выход)", end="")
        if args.duration > 0:
            print(f", duration={args.duration} с", end="")
        if log_file:
            print(f", лог → {args.log_path}", end="")
        print("\n")

        while True:
            time.sleep(args.interval)
            if deadline is not None and time.monotonic() >= deadline:
                break
            ob = stream.get_snapshot()
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            if not bids and not asks:
                print("  (ожидание snapshot…)")
                continue
            best_bid = bids[0] if bids else [0, 0]
            best_ask = asks[0] if asks else [0, 0]
            spread = best_ask[0] - best_bid[0] if (bids and asks) else 0
            u = ob.get("u", 0)
            line = f"  bid {best_bid[0]:.2f} x {best_bid[1]:.4f}  |  ask {best_ask[0]:.2f} x {best_ask[1]:.4f}  spread {spread:.2f}  u={u}"
            print(line)
            if log_file:
                ts = int(time.time())
                log_file.write(f"{ts}\t{best_bid[0]:.2f}\t{best_bid[1]:.4f}\t{best_ask[0]:.2f}\t{best_ask[1]:.4f}\t{spread:.2f}\t{u}\n")
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
