"""
Пути и каталоги для исторических данных (тики, стакан) для бэктеста песочницы.

Корень: HISTORY_DATA_DIR из конфига или data/history/ в корне проекта.
Структура: trades/{symbol}/ или trades/{symbol}/{year}/ (одна папка на год).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def get_history_root() -> Path:
    """Корневой каталог исторических данных (data/history или из конфига)."""
    try:
        from ..core import config
        root = getattr(config, "HISTORY_DATA_DIR", None)
        if root is None or (isinstance(root, str) and not root.strip()):
            root = Path(getattr(config, "PROJECT_ROOT", Path(__file__).resolve().parents[2])) / "data" / "history"
        elif isinstance(root, str):
            root = Path(root)
        return Path(root)
    except Exception:
        return Path(__file__).resolve().parents[2] / "data" / "history"


def get_trades_dir(symbol: str, year: str | None = None) -> Path:
    """
    Каталог CSV тиков для символа: history_root/trades/{symbol}/ или trades/{symbol}/{year}/.
    year — опционально, например "2025"; при задании файлы ожидаются в подпапке по году.
    """
    root = get_history_root()
    sym = (symbol or "").strip().upper() or "BTCUSDT"
    base = root / "trades" / sym
    if year and len(year) >= 4 and year[:4].isdigit():
        return base / year[:4]
    return base


def _extract_date_from_path(p: Path) -> str:
    """Из имени файла извлечь date_str (YYYY-MM-DD) для сортировки."""
    stem = p.stem
    if p.suffix == ".gz" and stem.endswith(".csv"):
        stem = stem[:-4]
    match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
    if match:
        return match.group(1)
    for sep in ("-", "_"):
        if sep in stem:
            parts = stem.split(sep)
            if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 4:
                return sep.join(parts[:3])
    return stem


def list_trade_files(symbol: str) -> list[tuple[Path, str]]:
    """
    Список файлов тиков по символу: (path, date_str).
    Ищет файлы в trades/{symbol}/ (плоская структура) и в trades/{symbol}/{year}/ (папка на год).
    date_str — дата из имени файла (YYYY-MM-DD) для сортировки.
    Поддерживаются .csv и .csv.gz.
    """
    dir_path = get_trades_dir(symbol)
    if not dir_path.is_dir():
        return []
    out: list[tuple[Path, str]] = []

    def collect_from(d: Path) -> None:
        for p in d.iterdir():
            if p.name.startswith("."):
                continue
            if p.is_file():
                if p.suffix not in (".csv", ".gz"):
                    continue
                date_str = _extract_date_from_path(p)
                out.append((p, date_str))
            elif p.is_dir() and len(p.name) == 4 and p.name.isdigit():
                collect_from(p)

    collect_from(dir_path)
    out.sort(key=lambda x: x[1])
    return out


def list_downloaded_trades(symbol: str) -> list[str]:
    """Список дат (YYYY-MM-DD), по которым есть файлы тиков."""
    files = list_trade_files(symbol)
    seen: set[str] = set()
    result: list[str] = []
    for _, date_str in files:
        if len(date_str) >= 10 and date_str[:10] not in seen:
            seen.add(date_str[:10])
            result.append(date_str[:10])
    return sorted(result)
