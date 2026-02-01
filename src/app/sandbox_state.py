"""
Общее состояние песочницы микроструктуры для доступа из основного цикла и Telegram-бота.

Основной цикл (bot_loop) записывает последнее состояние после каждого тика;
Telegram-бот читает его по команде /sandbox для отображения в реальном времени.
"""
from __future__ import annotations

from typing import Any

# Последнее состояние report["microstructure_sandbox"] (dict или None)
_last_state: dict[str, Any] | None = None


def set_last_state(state: dict[str, Any] | None) -> None:
    """Записать последнее состояние песочницы (вызывается из bot_loop)."""
    global _last_state
    _last_state = state


def get_last_state() -> dict[str, Any] | None:
    """Прочитать последнее состояние песочницы (для Telegram и др.)."""
    return _last_state
