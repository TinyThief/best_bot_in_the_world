"""
Юнит-тесты для модуля сигнала по микроструктуре (microstructure_signal).
Запуск из корня: python -m pytest tests/unit/test_microstructure_signal.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def _of(delta_ratio: float = 0.0, imbalance_ratio: float = 0.5, last_sweep_side: str | None = None) -> dict:
    """Минимальный mock результата analyze_orderflow()."""
    return {
        "dom": {"imbalance_ratio": imbalance_ratio, "raw_bid_volume": 100.0, "raw_ask_volume": 100.0},
        "time_and_sales": {"total_volume": 200.0, "volume_per_sec": 1.0},
        "volume_delta": {"delta_ratio": delta_ratio, "delta": 0.0, "buy_volume": 100.0, "sell_volume": 100.0},
        "sweeps": {"last_sweep_side": last_sweep_side, "last_sweep_time": None},
    }


def test_returns_expected_keys() -> None:
    """compute_microstructure_signal возвращает direction, confidence, reason, details."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    res = compute_microstructure_signal(_of(0.2, 0.6))
    assert "direction" in res
    assert "confidence" in res
    assert "reason" in res
    assert "details" in res
    assert res["direction"] in ("long", "short", "none")
    assert 0 <= res["confidence"] <= 1
    assert "score" in res["details"]
    assert "delta_ratio" in res["details"]
    assert "imbalance_ratio" in res["details"]


def test_long_when_delta_positive_and_imbalance_bid() -> None:
    """При положительной дельте и перевесе bid ожидаем long."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    res = compute_microstructure_signal(_of(delta_ratio=0.25, imbalance_ratio=0.62))
    assert res["direction"] == "long"
    assert res["confidence"] > 0.2
    assert res["details"]["score"] > 0


def test_short_when_delta_negative_and_imbalance_ask() -> None:
    """При отрицательной дельте и перевесе ask ожидаем short."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    res = compute_microstructure_signal(_of(delta_ratio=-0.25, imbalance_ratio=0.38))
    assert res["direction"] == "short"
    assert res["confidence"] > 0.2
    assert res["details"]["score"] < 0


def test_none_when_neutral() -> None:
    """При нейтральных delta и imbalance ожидаем none (или слабый сигнал)."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    res = compute_microstructure_signal(_of(0.0, 0.5), min_score_for_direction=0.25)
    assert res["direction"] == "none"
    assert res["details"]["score"] >= -0.25
    assert res["details"]["score"] <= 0.25


def test_sweep_bid_boosts_long() -> None:
    """После sweep низа (bid) вклад в сторону long."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    neutral = _of(0.0, 0.5, last_sweep_side=None)
    with_sweep_bid = _of(0.0, 0.5, last_sweep_side="bid")
    res_neutral = compute_microstructure_signal(neutral, min_score_for_direction=0.2)
    res_sweep = compute_microstructure_signal(with_sweep_bid, min_score_for_direction=0.2)
    assert res_sweep["details"]["sweep_contribution"] > 0
    assert res_sweep["details"]["score"] > res_neutral["details"]["score"]


def test_sweep_ask_boosts_short() -> None:
    """После sweep верха (ask) вклад в сторону short."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    with_sweep_ask = _of(0.0, 0.5, last_sweep_side="ask")
    res = compute_microstructure_signal(with_sweep_ask, min_score_for_direction=0.2)
    assert res["details"]["sweep_contribution"] < 0
    assert res["details"]["score"] < 0


def test_empty_orderflow_returns_none() -> None:
    """Пустой of_result даёт none и нулевую уверенность."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    res = compute_microstructure_signal({})
    assert res["direction"] == "none"
    assert res["confidence"] == 0.0
    assert res["details"]["score"] == 0.0
    assert res["details"]["delta_ratio"] == 0.0
    assert res["details"]["imbalance_ratio"] == 0.5


def test_strict_threshold_gives_none() -> None:
    """Высокий min_score_for_direction даёт none при умеренном score."""
    from src.analysis.microstructure_signal import compute_microstructure_signal

    res = compute_microstructure_signal(
        _of(delta_ratio=0.2, imbalance_ratio=0.55),
        min_score_for_direction=0.9,
    )
    assert res["direction"] == "none"
    assert res["details"]["score"] < 0.9


def _run_tests() -> None:
    """Запуск всех test_* без pytest: python tests/unit/test_microstructure_signal.py"""
    import inspect
    mod = __import__(__name__)
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if name.startswith("test_"):
            fn()
            print(f"  OK {name}")


if __name__ == "__main__":
    print("Тесты microstructure_signal")
    _run_tests()
    print("Все тесты пройдены.")
