"""Тест модуля торговых зон: загрузка свечей, detect_trading_zones, вывод результата."""
import sys

from ..core import config
from ..core.database import get_connection, get_candles
from ..analysis.trading_zones import detect_trading_zones

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def run(tf: str = "240", limit: int = 300) -> None:
    symbol = config.SYMBOL
    conn = get_connection()
    cur = conn.cursor()
    try:
        candles = get_candles(cur, symbol, tf, limit=limit, order_asc=True)
    finally:
        conn.close()
    if not candles:
        print("No candles in DB for %s %s. Run bin/accumulate_db.py or use exchange." % (symbol, tf))
        return
    print("Candles: %s (TF=%s, symbol=%s)" % (len(candles), tf, symbol))
    result = detect_trading_zones(candles)
    print()
    print("=== Trading zones result ===")
    print("  close: %.2f" % result.get("close"))
    print("  zone_low: %s | zone_high: %s" % (result.get("zone_low"), result.get("zone_high")))
    print("  in_zone: %s | at_support_zone: %s | at_resistance_zone: %s" % (
        result.get("in_zone"), result.get("at_support_zone"), result.get("at_resistance_zone")))
    print("  distance_to_support_pct: %s | distance_to_resistance_pct: %s" % (
        result.get("distance_to_support_pct"), result.get("distance_to_resistance_pct")))
    ns, nr = result.get("nearest_support"), result.get("nearest_resistance")
    if ns:
        print("  nearest_support: %.2f (origin=%s, current=%s, broken=%s, zone=%.2f–%.2f, strength=%.2f)" % (
            ns.get("price"), ns.get("origin_role"), ns.get("current_role"), ns.get("broken"),
            ns.get("level_zone_low"), ns.get("level_zone_high"), ns.get("strength", 0)))
    if nr:
        print("  nearest_resistance: %.2f (origin=%s, current=%s, broken=%s, zone=%.2f–%.2f, strength=%.2f)" % (
            nr.get("price"), nr.get("origin_role"), nr.get("current_role"), nr.get("broken"),
            nr.get("level_zone_low"), nr.get("level_zone_high"), nr.get("strength", 0)))
    rf = result.get("recent_flips") or []
    print("  recent_flips: %s" % len(rf))
    for lev in rf[:5]:
        print("    %.2f: %s -> %s (broken_at_bar=%s)" % (
            lev.get("price"), lev.get("origin_role"), lev.get("current_role"), lev.get("broken_at_bar")))
    levels = result.get("levels") or []
    print("  levels count: %s" % len(levels))
    print("  Levels (all): price | origin | current | broken | touches | volume_at_level | zone_low–zone_high | recency | round_bonus | strength")
    for lev in levels[:10]:
        print("    %.2f | %s | %s | %s | %s | %s | %.2f–%.2f | %s | %s | %.2f" % (
            lev.get("price"), lev.get("origin_role"), lev.get("current_role"), lev.get("broken"),
            lev.get("touches"), lev.get("volume_at_level"),
            lev.get("level_zone_low"), lev.get("level_zone_high"),
            lev.get("recency"), lev.get("round_bonus"), lev.get("strength", 0)))
    print()
    print("Done.")


if __name__ == "__main__":
    tf = "240"
    limit = 300
    if len(sys.argv) > 1:
        tf = sys.argv[1]
    if len(sys.argv) > 2:
        limit = int(sys.argv[2])
    run(tf=tf, limit=limit)
