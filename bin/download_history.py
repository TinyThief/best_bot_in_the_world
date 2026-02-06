"""Инструкции и проверка каталога для исторических данных (тики Bybit).

Без --download: показывает URL, целевой каталог и список уже скачанных файлов.
С --download: скачивает тики с public.bybit.com за диапазон дат в trades/{symbol}/{year}/ (папка на год).

Запуск из корня:
  python bin/download_history.py [--list] [--mkdir] [--symbol BTCUSDT]
  python bin/download_history.py --download --from 2025-01-01 --to 2025-12-31 [--symbol BTCUSDT]
"""
from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.core import config
from src.history.storage import get_history_root, get_trades_dir, list_trade_files, list_downloaded_trades

BYBIT_HISTORY_URL = "https://www.bybit.com/derivatives/en/history-data"
BYBIT_PUBLIC_TRADING_BASE = "https://public.bybit.com/trading/"

DOWNLOAD_SLEEP_SEC = 1.0
DOWNLOAD_MAX_RETRIES = 5
DOWNLOAD_RETRY_BACKOFF_SEC = 1.0


def _download_one_date(
    symbol: str,
    date_str: str,
    out_dir: Path,
) -> bool:
    """Скачивает один день с public.bybit.com: .csv.gz → распаковка в .csv. Возвращает True при успехе."""
    import requests

    url = f"{BYBIT_PUBLIC_TRADING_BASE}{symbol}/{symbol}{date_str}.csv.gz"
    out_csv = out_dir / f"{symbol}{date_str}.csv"
    if out_csv.exists():
        print(f"  {date_str}: уже есть {out_csv.name}, пропуск")
        return True

    last_error = None
    for attempt in range(DOWNLOAD_MAX_RETRIES):
        try:
            r = requests.get(url, timeout=60, stream=True)
            if r.status_code == 404:
                print(f"  {date_str}: нет на сервере (404)")
                return False
            r.raise_for_status()
            # Скачиваем в память, распаковываем в .csv
            raw = r.content
            if not raw:
                print(f"  {date_str}: пустой ответ")
                return False
            decompressed = gzip.decompress(raw)
            out_csv.write_bytes(decompressed)
            print(f"  {date_str}: сохранён {out_csv.name}")
            return True
        except requests.RequestException as e:
            last_error = e
            if attempt < DOWNLOAD_MAX_RETRIES - 1:
                delay = DOWNLOAD_RETRY_BACKOFF_SEC * (2**attempt)
                print(f"  {date_str}: ошибка {e}, повтор через {delay:.0f} с...")
                time.sleep(delay)
    print(f"  {date_str}: не удалось после {DOWNLOAD_MAX_RETRIES} попыток: {last_error}")
    return False


def _run_download(symbol: str, date_from: str, date_to: str) -> None:
    """Цикл по датам: скачать каждый день в папку года trades/{symbol}/{year}/."""
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError as e:
        print(f"Ошибка формата даты (ожидается YYYY-MM-DD): {e}")
        sys.exit(1)
    if start > end:
        print("Дата --from должна быть не позже --to")
        sys.exit(1)

    base_dir = get_trades_dir(symbol)
    base_dir.mkdir(parents=True, exist_ok=True)
    print(f"Скачивание тиков {symbol} с {date_from} по {date_to} (папки по году: {base_dir}/YYYY/)")
    print()

    ok = 0
    fail = 0
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        year = date_str[:4]
        out_dir = get_trades_dir(symbol, year)
        out_dir.mkdir(parents=True, exist_ok=True)
        if _download_one_date(symbol, date_str, out_dir):
            ok += 1
        else:
            fail += 1
        current += timedelta(days=1)
        if current <= end:
            time.sleep(DOWNLOAD_SLEEP_SEC)

    print()
    print(f"Готово: успешно {ok}, недоступно/ошибок {fail}")


def _organize_by_year(symbol: str) -> None:
    """Переносит CSV/CSV.GZ из trades/{symbol}/ в подпапки по году: trades/{symbol}/{year}/."""
    base_dir = get_trades_dir(symbol)
    if not base_dir.is_dir():
        print(f"Каталог не найден: {base_dir}")
        return
    moved = 0
    skipped = 0
    for p in base_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix not in (".csv", ".gz") or p.name.startswith("."):
            continue
        match = re.search(r"(\d{4}-\d{2}-\d{2})", p.stem)
        if not match:
            skipped += 1
            continue
        date_str = match.group(1)
        year = date_str[:4]
        target_dir = get_trades_dir(symbol, year)
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / p.name
        if dest.resolve() == p.resolve():
            continue
        if dest.exists():
            print(f"  пропуск (уже есть): {p.name} -> {target_dir}/")
            skipped += 1
            continue
        shutil.move(str(p), str(dest))
        print(f"  {p.name} -> {target_dir}/")
        moved += 1
    print(f"Готово: перенесено {moved}, пропущено {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Инструкции по загрузке исторических данных Bybit и проверка каталога"
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="Показать уже скачанные файлы тиков по символу",
    )
    parser.add_argument(
        "--mkdir",
        action="store_true",
        help="Создать целевой каталог trades/{symbol}/ если его нет",
    )
    parser.add_argument(
        "--symbol",
        "-s",
        type=str,
        default="",
        help="Символ (по умолчанию из конфига SYMBOL)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Скачать тики с public.bybit.com за диапазон дат",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        metavar="YYYY-MM-DD",
        type=str,
        default="",
        help="Начало диапазона (обязательно при --download)",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        metavar="YYYY-MM-DD",
        type=str,
        default="",
        help="Конец диапазона (обязательно при --download)",
    )
    parser.add_argument(
        "--organize-by-year",
        action="store_true",
        help="Раскидать существующие CSV из trades/{symbol}/ по папкам года trades/{symbol}/{year}/",
    )
    args = parser.parse_args()

    symbol = (args.symbol or getattr(config, "SYMBOL", "BTCUSDT") or "BTCUSDT").strip().upper()
    root = get_history_root()
    trades_dir = get_trades_dir(symbol)

    if args.download:
        if not args.date_from or not args.date_to:
            print("При --download укажи --from YYYY-MM-DD и --to YYYY-MM-DD")
            sys.exit(1)
        _run_download(symbol, args.date_from.strip(), args.date_to.strip())
        sys.exit(0)

    if args.organize_by_year:
        print(f"Раскладываю тики {symbol} по папкам года в {get_trades_dir(symbol)}")
        _organize_by_year(symbol)
        sys.exit(0)

    # Режим без скачивания: инструкция + --list / --mkdir
    print("Исторические данные Bybit (тики для бэктеста песочницы)")
    print("-" * 60)
    print(f"Страница загрузки: {BYBIT_HISTORY_URL}")
    print("Выбери: Derivatives -> Linear Perpetual -> Trades -> нужная дата -> скачай CSV.")
    print("Либо скачай автоматически: python bin/download_history.py --download --from YYYY-MM-DD --to YYYY-MM-DD")
    print("Распакуй и положи файлы в каталог:")
    print(f"  {trades_dir}")
    print()

    if args.mkdir:
        trades_dir.mkdir(parents=True, exist_ok=True)
        print(f"Каталог создан: {trades_dir}")
        print()

    if args.list:
        files = list_trade_files(symbol)
        dates = list_downloaded_trades(symbol)
        if not files:
            print(f"Файлов тиков для {symbol} пока нет.")
        else:
            print(f"Файлы тиков для {symbol}: {len(files)} файл(ов), дат: {len(dates)}")
            for path, date_str in files[:30]:
                print(f"  {path.name}  ({date_str})")
            if len(files) > 30:
                print(f"  ... и ещё {len(files) - 30}")
            print(f"Доступные даты (YYYY-MM-DD): {', '.join(dates[:15])}{'...' if len(dates) > 15 else ''}")
        print()

    print("Корень исторических данных:", root)
    sys.exit(0)


if __name__ == "__main__":
    main()
