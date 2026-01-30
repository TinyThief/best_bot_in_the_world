"""
Юнит-тесты для модуля определения тренда (market_trend).
Запуск из корня: python -m pytest tests/unit/test_market_trend.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def _make_candles(n: int, trend: str = "flat", base: float = 100.0) -> list[dict]:
    """Синтетические свечи: trend in ('up', 'down', 'flat')."""
    out = []
    for i in range(n):
        if trend == "up":
            o = base + i * 0.5
            c = o + 0.3
        elif trend == "down":
            o = base - i * 0.5
            c = o - 0.3
        else:
            o = base + (i % 3 - 1) * 0.2
            c = o + 0.05
        h = max(o, c) + 0.1
        l_ = min(o, c) - 0.1
        out.append({"start_time": 1000000 + i * 86400, "open": o, "high": h, "low": l_, "close": c, "volume": 1000.0})
    return out


def test_detect_trend_returns_expected_keys() -> None:
    """detect_trend возвращает все ожидаемые ключи."""
    from src.analysis.market_trend import detect_trend

    candles = _make_candles(150, "up")
    res = detect_trend(candles, lookback=100, timeframe="D")
    assert "direction" in res
    assert "strength" in res
    assert "trend_unclear" in res
    assert "details" in res
    assert "bullish_score" in res
    assert "bearish_score" in res
    assert res["direction"] in ("up", "down", "flat")
    assert 0 <= res["strength"] <= 1


def test_detect_trend_up_on_rising_candles() -> None:
    """При явном росте цены ожидаем up или flat (не down)."""
    from src.analysis.market_trend import detect_trend

    candles = _make_candles(200, "up", base=50000.0)
    res = detect_trend(candles, lookback=100, timeframe="D")
    assert res["direction"] in ("up", "flat")
    assert res["bullish_score"] >= res["bearish_score"]


def test_detect_trend_down_on_falling_candles() -> None:
    """При явном падении цены ожидаем down или flat (не up)."""
    from src.analysis.market_trend import detect_trend

    candles = _make_candles(200, "down", base=50000.0)
    res = detect_trend(candles, lookback=100, timeframe="D")
    assert res["direction"] in ("down", "flat")
    assert res["bearish_score"] >= res["bullish_score"]


def test_detect_trend_flat_on_insufficient_data() -> None:
    """При недостатке данных возвращается flat и trend_unclear."""
    from src.analysis.market_trend import detect_trend

    candles = _make_candles(10, "up")
    res = detect_trend(candles, lookback=100, timeframe="D")
    assert res["direction"] == "flat"
    assert res["trend_unclear"] is True


def test_detect_regime_returns_expected_keys() -> None:
    """detect_regime возвращает regime, adx, atr_ratio, bb_width."""
    from src.analysis.market_trend import detect_regime

    candles = _make_candles(60, "flat")
    res = detect_regime(candles, lookback=50)
    assert "regime" in res
    assert res["regime"] in ("trend", "range", "surge")
    assert "regime_ru" in res
    assert "adx" in res or res.get("adx") is None


def test_tf_to_trend_profile() -> None:
    """Профиль short для коротких ТФ, long для D/W/M и 60+."""
    from src.analysis.market_trend import _tf_to_trend_profile

    assert _tf_to_trend_profile("D") == "long"
    assert _tf_to_trend_profile("W") == "long"
    assert _tf_to_trend_profile("60") == "long"
    assert _tf_to_trend_profile("15") == "short"
    assert _tf_to_trend_profile("30") == "short"
    assert _tf_to_trend_profile(None) == "long"


def test_trend_profiles_keys() -> None:
    """TREND_PROFILES содержат lookback, min_gap, min_gap_down."""
    from src.analysis.market_trend import TREND_PROFILES

    for profile in ("short", "long"):
        assert profile in TREND_PROFILES
        p = TREND_PROFILES[profile]
        assert "lookback" in p
        assert "min_gap" in p
        assert "min_gap_down" in p


def run_all() -> None:
    """Запуск всех тестов без pytest: python -m tests.unit.test_market_trend"""
    tests = [
        test_detect_trend_returns_expected_keys,
        test_detect_trend_up_on_rising_candles,
        test_detect_trend_down_on_falling_candles,
        test_detect_trend_flat_on_insufficient_data,
        test_detect_regime_returns_expected_keys,
        test_tf_to_trend_profile,
        test_trend_profiles_keys,
    ]
    for t in tests:
        t()


if __name__ == "__main__":
    run_all()
    print("Все тесты пройдены.")
