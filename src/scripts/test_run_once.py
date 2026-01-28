"""Один прогон анализа: мультиТФ, 6 фаз, сигналы. Для теста."""
import sys

from ..analysis.multi_tf import analyze_multi_timeframe

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def run() -> None:
    r = analyze_multi_timeframe()
    print("=== Signal ===")
    print("Direction:", r["signals"]["direction"])
    print("Reason:", r["signals"]["reason"])
    print()
    print("=== Higher TF ===")
    print("Trend:", r["higher_tf_trend"])
    print("Phase (id):", r.get("higher_tf_phase", "-"))
    print("Phase (RU):", r.get("higher_tf_phase_ru", "-"))
    print()
    print("=== Per timeframe ===")
    for tf, d in r.get("timeframes", {}).items():
        trend = d.get("trend", "?")
        phase = d.get("phase", "-")
        phase_ru = d.get("phase_ru", "-")
        n = len(d.get("candles", []))
        print("  TF %s: trend=%s, phase=%s (%s), candles=%s" % (tf, trend, phase, phase_ru, n))
    print()
    print("Done.")


if __name__ == "__main__":
    run()
