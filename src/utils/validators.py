"""
Валидация данных (конфиг, ответы API, сигналы).
Расширять по мере надобности.
"""
from __future__ import annotations


def validate_symbol(symbol: str) -> bool:
    """Проверка формата символа (например BTCUSDT)."""
    return bool(symbol and symbol.isupper() and len(symbol) >= 2)


def validate_timeframe(tf: str) -> bool:
    """Проверка таймфрейма Bybit: 1,3,5,15,30,60,120,240,360,720,D,W,M."""
    if tf in ("D", "W", "M"):
        return True
    try:
        n = int(tf)
        return n > 0
    except ValueError:
        return False
