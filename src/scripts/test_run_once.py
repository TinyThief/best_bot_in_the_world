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
    print("Momentum: %s (%s), direction=%s, RSI=%s" % (
        r.get("higher_tf_momentum_state", "neutral"),
        r.get("higher_tf_momentum_state_ru", "—"),
        r.get("higher_tf_momentum_direction_ru", "—"),
        r.get("higher_tf_momentum_rsi"),
    ))
    print()
    print("=== Per timeframe ===")
    for tf, d in r.get("timeframes", {}).items():
        trend = d.get("trend", "?")
        phase = d.get("phase", "-")
        phase_ru = d.get("phase_ru", "-")
        n = len(d.get("candles", []))
        print("  TF %s: trend=%s, phase=%s (%s), candles=%s" % (tf, trend, phase, phase_ru, n))
    print()
    # Торговые зоны (по старшему ТФ)
    zones = r.get("trading_zones") or {}
    if zones.get("levels"):
        print("=== Trading zones (higher TF) ===")
        print("  Zone: %s – %s | in_zone=%s | at_support=%s at_resistance=%s | levels_with_confluence=%s" % (
            zones.get("zone_low"), zones.get("zone_high"),
            zones.get("in_zone"), zones.get("at_support_zone"), zones.get("at_resistance_zone"),
            zones.get("levels_with_confluence", 0)))
        ns, nr = zones.get("nearest_support"), zones.get("nearest_resistance")
        if ns:
            print("  Nearest support: %.2f (origin=%s, current=%s, broken=%s, strength=%.2f)" % (
                ns.get("price"), ns.get("origin_role"), ns.get("current_role"), ns.get("broken"), ns.get("strength", 0)))
        if nr:
            print("  Nearest resistance: %.2f (origin=%s, current=%s, broken=%s, strength=%.2f)" % (
                nr.get("price"), nr.get("origin_role"), nr.get("current_role"), nr.get("broken"), nr.get("strength", 0)))
        rf = zones.get("recent_flips") or []
        print("  Recent flips: %s" % len(rf))
        for lev in rf[:3]:
            print("    %.2f: %s -> %s" % (lev.get("price"), lev.get("origin_role"), lev.get("current_role")))
        print("  Levels (top 5): price | origin | current | touches | vol_at_level | recency | round_bonus | strength")
        for lev in (zones.get("levels") or [])[:5]:
            print("    %.2f | %s | %s | %s | %s | %s | %s | %.2f" % (
                lev.get("price"), lev.get("origin_role"), lev.get("current_role"),
                lev.get("touches"), lev.get("volume_at_level"), lev.get("recency"), lev.get("round_bonus"), lev.get("strength", 0)))
    else:
        print("=== Trading zones === (no levels)")
    print()
    print("Done.")


if __name__ == "__main__":
    run()
