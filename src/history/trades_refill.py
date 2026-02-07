"""
Подгрузка недостающих тиков: по API (как для свечей) и с public.bybit.com.

- get_missing_dates(symbol, date_from, date_to) — список дат без файла.
- refill_ticks_from_public(symbol, date_from, date_to) — скачивание с public.bybit.com за недостающие даты.
- refill_ticks_today_from_api(symbol) — последние сделки по REST API, запись в CSV за сегодня.
- ensure_ticks(symbol, date_from, date_to) — одна точка входа: сначала public, затем при необходимости API за сегодня.
"""
from __future__ import annotations

import csv
import gzip
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .storage import get_trades_dir, list_downloaded_trades

logger = logging.getLogger(__name__)

BYBIT_PUBLIC_TRADING_BASE = "https://public.bybit.com/trading/"
DOWNLOAD_SLEEP_SEC = 1.0
DOWNLOAD_MAX_RETRIES = 5
DOWNLOAD_RETRY_BACKOFF_SEC = 1.0


def get_missing_dates(
    symbol: str,
    date_from: str,
    date_to: str,
) -> list[str]:
    """
    Возвращает список дат YYYY-MM-DD в диапазоне [date_from, date_to],
    для которых ещё нет файла тиков в trades/{symbol}/{year}/.
    """
    have = set(list_downloaded_trades(symbol))
    out: list[str] = []
    try:
        start = datetime.strptime(date_from.strip(), "%Y-%m-%d").date()
        end = datetime.strptime(date_to.strip(), "%Y-%m-%d").date()
    except ValueError:
        return out
    if start > end:
        return out
    current = start
    while current <= end:
        d_str = current.strftime("%Y-%m-%d")
        if d_str not in have:
            out.append(d_str)
        current += timedelta(days=1)
    return out


def download_ticks_from_public(
    symbol: str,
    date_str: str,
    *,
    skip_existing: bool = True,
) -> bool:
    """
    Скачивает тики за одну дату (YYYY-MM-DD) с public.bybit.com в trades/{symbol}/{year}/.
    Возвращает True при успехе, False при 404 или ошибке.
    """
    try:
        import requests
    except ImportError:
        logger.warning("Подгрузка тиков с public.bybit.com требует requests")
        return False

    sym = (symbol or "").strip().upper() or "BTCUSDT"
    year = date_str[:4]
    out_dir = get_trades_dir(sym, year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"{sym}{date_str}.csv"
    if skip_existing and out_csv.exists():
        return True

    url = f"{BYBIT_PUBLIC_TRADING_BASE}{sym}/{sym}{date_str}.csv.gz"
    last_err: Exception | None = None
    for attempt in range(DOWNLOAD_MAX_RETRIES):
        try:
            r = requests.get(url, timeout=60, stream=True)
            if r.status_code == 404:
                logger.debug("Тики за %s для %s: нет на сервере (404)", date_str, sym)
                return False
            r.raise_for_status()
            raw = r.content
            if not raw:
                return False
            decompressed = gzip.decompress(raw)
            out_csv.write_bytes(decompressed)
            logger.info("Тики за %s для %s: сохранён %s", date_str, sym, out_csv.name)
            return True
        except requests.RequestException as e:
            last_err = e
            if attempt < DOWNLOAD_MAX_RETRIES - 1:
                delay = DOWNLOAD_RETRY_BACKOFF_SEC * (2 ** attempt)
                logger.warning("Тики за %s: %s, повтор через %.0f с", date_str, e, delay)
                time.sleep(delay)
    logger.warning("Тики за %s: не удалось после %s попыток: %s", date_str, DOWNLOAD_MAX_RETRIES, last_err)
    return False


def refill_ticks_from_public(
    symbol: str,
    date_from: str,
    date_to: str,
    *,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """
    Подгружает тики с public.bybit.com за все недостающие даты в [date_from, date_to].
    Возвращает: {"downloaded": int, "skipped": int, "failed": list[str]}.
    """
    missing = get_missing_dates(symbol, date_from, date_to)
    if not missing:
        return {"downloaded": 0, "skipped": 0, "failed": []}

    downloaded = 0
    failed: list[str] = []
    for d in missing:
        if download_ticks_from_public(symbol, d, skip_existing=skip_existing):
            downloaded += 1
        else:
            failed.append(d)
        time.sleep(DOWNLOAD_SLEEP_SEC)
    skipped = len(missing) - downloaded - len(failed)
    return {"downloaded": downloaded, "skipped": skipped, "failed": failed}


def _trades_to_csv_rows(trades: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Преобразует сделки из формата orderflow (T, symbol, side, size, price, id) в строки для CSV."""
    rows: list[dict[str, str]] = []
    for t in trades:
        t_ms = t.get("T") or 0
        # Формат как у public.bybit.com: timestamp в секундах с дробной частью
        ts_sec = t_ms / 1000.0
        rows.append({
            "timestamp": str(ts_sec),
            "symbol": t.get("symbol", ""),
            "side": t.get("side", ""),
            "size": str(t.get("size", 0)),
            "price": str(t.get("price", 0)),
            "id": t.get("id", ""),
        })
    return rows


def refill_ticks_today_from_api(
    symbol: str,
    *,
    category: str | None = None,
    limit: int = 1000,
    merge_with_existing: bool = True,
) -> int:
    """
    Загружает последние сделки по REST API и записывает их в CSV за сегодня.
    Если merge_with_existing и файл за сегодня уже есть — подгружает только новые (по id) и дописывает.
    Возвращает число записанных строк.
    """
    from ..core import config
    from ..core.exchange import get_recent_public_trades

    sym = (symbol or getattr(config, "SYMBOL", "BTCUSDT") or "BTCUSDT").strip().upper()
    today_str = date.today().strftime("%Y-%m-%d")
    year = today_str[:4]
    out_dir = get_trades_dir(sym, year)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"{sym}{today_str}.csv"

    trades = get_recent_public_trades(symbol=sym, category=category or getattr(config, "BYBIT_CATEGORY", "linear"), limit=limit)
    if not trades:
        return 0

    existing_ids: set[str] = set()
    existing_rows: list[dict[str, str]] = []
    if merge_with_existing and out_csv.exists():
        try:
            with open(out_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
                for row in reader:
                    existing_rows.append(row)
                    eid = row.get("id") or row.get("trdMatchID") or ""
                    if eid:
                        existing_ids.add(eid)
        except Exception as e:
            logger.warning("Не удалось прочитать существующий файл тиков за сегодня: %s", e)

    new_trades = [t for t in trades if (t.get("id") or "") not in existing_ids]
    if not new_trades:
        return 0

    new_rows = _trades_to_csv_rows(new_trades)
    all_rows = existing_rows + new_rows
    # Сортируем по timestamp
    try:
        all_rows.sort(key=lambda r: float(r.get("timestamp", 0)))
    except (TypeError, ValueError):
        pass

    fieldnames = ["timestamp", "symbol", "side", "size", "price", "id"]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info("Тики за сегодня (%s): записано %s новых (всего %s)", today_str, len(new_rows), len(all_rows))
    return len(new_rows)


def ensure_ticks(
    symbol: str,
    date_from: str,
    date_to: str,
    *,
    use_public: bool = True,
    use_api_today: bool = True,
) -> dict[str, Any]:
    """
    Одна точка входа: подгружает тики, которых не хватает в диапазоне [date_from, date_to].
    1) За недостающие даты — скачивание с public.bybit.com (use_public=True).
    2) Если в диапазон входит сегодня и use_api_today — дополнение за сегодня из REST API.
    Возвращает сводку: missing_before, refill_public (downloaded, failed), refill_api_today (count).
    """
    missing_before = get_missing_dates(symbol, date_from, date_to)
    result: dict[str, Any] = {
        "missing_before": len(missing_before),
        "refill_public": None,
        "refill_api_today": 0,
    }

    if use_public and missing_before:
        result["refill_public"] = refill_ticks_from_public(symbol, date_from, date_to, skip_existing=True)

    today_str = date.today().strftime("%Y-%m-%d")
    in_range = date_from <= today_str <= date_to
    if use_api_today and in_range:
        result["refill_api_today"] = refill_ticks_today_from_api(symbol, merge_with_existing=True)

    return result
