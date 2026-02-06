"""Проверка модуля src.history: пути, список файлов, load_trades/iter_trades без данных."""
from __future__ import annotations

import unittest
from pathlib import Path


class TestHistory(unittest.TestCase):
    def test_import(self) -> None:
        from src.history import (
            get_history_root,
            get_trades_dir,
            list_trade_files,
            list_downloaded_trades,
            load_trades,
            iter_trades,
        )
        self.assertIsNotNone(get_history_root())
        self.assertIsNotNone(get_trades_dir("BTCUSDT"))

    def test_get_history_root_is_path(self) -> None:
        from src.history import get_history_root
        root = get_history_root()
        self.assertIsInstance(root, Path)
        self.assertTrue(root.is_absolute() or not str(root).startswith(".."))

    def test_get_trades_dir_contains_symbol(self) -> None:
        from src.history import get_history_root, get_trades_dir
        root = get_history_root()
        td = get_trades_dir("BTCUSDT")
        self.assertIn("BTCUSDT", str(td))
        self.assertEqual(td, root / "trades" / "BTCUSDT")

    def test_list_downloaded_trades_returns_list(self) -> None:
        from src.history import list_downloaded_trades
        dates = list_downloaded_trades("BTCUSDT")
        self.assertIsInstance(dates, list)

    def test_load_trades_empty_range(self) -> None:
        from src.history import load_trades
        trades = load_trades("BTCUSDT", date_from="2000-01-01", date_to="2000-01-02")
        self.assertIsInstance(trades, list)
        self.assertEqual(len(trades), 0)

    def test_iter_trades_empty_range(self) -> None:
        from src.history import iter_trades
        n = sum(1 for _ in iter_trades("BTCUSDT", date_from="2000-01-01", date_to="2000-01-02"))
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
