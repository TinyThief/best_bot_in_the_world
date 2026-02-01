"""
Микроструктура рынка и Order Flow: DOM, Time & Sales, Volume Delta, Sweeps.

Заготовка модуля — интерфейсы и заглушки. Полный дизайн: docs/ORDERFLOW_MICROSTRUCTURE.md.

Источники данных:
  - DOM, Sweeps (частично): OrderbookStream.get_snapshot() (уже есть).
  - T&S, Volume Delta: поток исполненных сделок — TradesStream (WebSocket publicTrade.{symbol}).
"""

from __future__ import annotations

from typing import Any


def _parse_levels(snapshot: dict[str, Any], side: str, depth_levels: int) -> list[tuple[float, float]]:
    """Из снимка стакана извлекает до depth_levels уровней для bid или ask. Возвращает [(price, size), ...]."""
    key = "bids" if side == "bid" else "asks"
    raw = snapshot.get(key) or []
    out: list[tuple[float, float]] = []
    for item in raw[:depth_levels]:
        try:
            p = float(item[0])
            s = float(item[1])
            if s > 0:
                out.append((p, s))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _wall_threshold(sizes: list[float], percentile: float) -> float:
    """Порог «стены»: размер выше percentile процента уровней. Если sizes пустой — 0."""
    if not sizes:
        return 0.0
    if len(sizes) == 1:
        return sizes[0]
    sorted_sizes = sorted(sizes)
    idx = min(int(len(sorted_sizes) * percentile / 100.0), len(sorted_sizes) - 1)
    return sorted_sizes[idx]


# ---------------------------------------------------------------------------
# 1. DOM (Depth of Market)
# ---------------------------------------------------------------------------


def analyze_dom(
    snapshot: dict[str, Any],
    *,
    depth_levels: int = 20,
    wall_percentile: float = 90.0,
) -> dict[str, Any]:
    """
    Анализ стакана заявок: уровни с большим объёмом (стены), bid/ask imbalance.

    snapshot: результат OrderbookStream.get_snapshot() — bids/asks [[price, size], ...], ts, u, seq.
    depth_levels: сколько уровней с каждой стороны учитывать.
    wall_percentile: уровень объёма выше этого перцентиля считается «стеной» (по размерам в срезе).

    Возвращает: clusters_bid, clusters_ask, imbalance_ratio, significant_levels, raw_bid_volume, raw_ask_volume.
    """
    bids = _parse_levels(snapshot, "bid", depth_levels)
    asks = _parse_levels(snapshot, "ask", depth_levels)

    bid_vol = sum(s for _, s in bids)
    ask_vol = sum(s for _, s in asks)
    total = bid_vol + ask_vol
    imbalance_ratio = (bid_vol / total) if total > 0 else 0.5

    all_sizes = [s for _, s in bids] + [s for _, s in asks]
    threshold = _wall_threshold(all_sizes, wall_percentile)

    clusters_bid: list[dict[str, Any]] = []
    clusters_ask: list[dict[str, Any]] = []
    significant_levels: list[dict[str, Any]] = []

    for price, size in bids:
        if size >= threshold and threshold > 0:
            lev = {"price": price, "size": size, "side": "bid", "type": "wall"}
            clusters_bid.append(lev)
            significant_levels.append(lev)

    for price, size in asks:
        if size >= threshold and threshold > 0:
            lev = {"price": price, "size": size, "side": "ask", "type": "wall"}
            clusters_ask.append(lev)
            significant_levels.append(lev)

    return {
        "clusters_bid": clusters_bid,
        "clusters_ask": clusters_ask,
        "imbalance_ratio": imbalance_ratio,
        "significant_levels": significant_levels,
        "raw_bid_volume": bid_vol,
        "raw_ask_volume": ask_vol,
    }


def _trades_in_window(trades: list[dict[str, Any]], window_end_ts_ms: int, window_sec: float) -> list[dict[str, Any]]:
    """Оставляет сделки с T в интервале [window_end_ts_ms - window_sec*1000, window_end_ts_ms]. Сделки считаются по T (мс)."""
    if not trades or window_sec <= 0:
        return []
    start_ms = int(window_end_ts_ms - window_sec * 1000)
    return [t for t in trades if (t.get("T") or 0) >= start_ms and (t.get("T") or 0) <= window_end_ts_ms]


def _volume_and_side(t: dict[str, Any]) -> tuple[float, str]:
    """Объём и сторона из сделки: поддерживает TradesStream (size, side) и сырой Bybit (v, S)."""
    vol = float(t.get("size") or t.get("v") or 0)
    side = str(t.get("side") or t.get("S") or "").strip().lower()
    return (vol, side)


# ---------------------------------------------------------------------------
# 2. Time & Sales (исполненные сделки)
# ---------------------------------------------------------------------------


def analyze_time_and_sales(
    trades: list[dict[str, Any]],
    *,
    window_sec: float = 60.0,
    volume_spike_mult: float = 2.0,
    now_ts_ms: int | None = None,
) -> dict[str, Any]:
    """
    Агрегация исполненных сделок: объём за окно, скорость (объём/сек), всплеск объёма.

    trades: список сделок из TradesStream — каждая с T (время мс), side (Buy/Sell), size (объём).
    window_sec: окно в секундах для агрегации.
    volume_spike_mult: во сколько раз текущий объём должен превысить средний для флага «всплеск».
    now_ts_ms: конец окна (мс); если None — берётся макс T по сделкам или 0.

    Возвращает: total_volume, buy_volume, sell_volume, volume_per_sec, is_volume_spike, trades_count.
    """
    if not trades:
        return {
            "total_volume": 0.0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "volume_per_sec": 0.0,
            "is_volume_spike": False,
            "trades_count": 0,
        }
    end_ts = now_ts_ms if now_ts_ms is not None else max((t.get("T") or 0) for t in trades)
    in_window = _trades_in_window(trades, end_ts, window_sec)
    half_sec = window_sec / 2.0
    first_half = _trades_in_window(trades, end_ts, half_sec)
    second_half_begin = int(end_ts - half_sec * 1000)
    second_half = [t for t in in_window if (t.get("T") or 0) >= second_half_begin]

    buy_vol = 0.0
    sell_vol = 0.0
    for t in in_window:
        vol, side = _volume_and_side(t)
        if "buy" in side:
            buy_vol += vol
        else:
            sell_vol += vol
    total_vol = buy_vol + sell_vol
    vol_per_sec = total_vol / window_sec if window_sec > 0 else 0.0

    vol_first = sum(_volume_and_side(t)[0] for t in first_half)
    vol_second = sum(_volume_and_side(t)[0] for t in second_half)
    # Всплеск: объём во второй половине окна в volume_spike_mult раз выше первой половины
    is_spike = (
        volume_spike_mult > 0 and vol_first > 0 and vol_second >= volume_spike_mult * vol_first
    )

    return {
        "total_volume": total_vol,
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "volume_per_sec": vol_per_sec,
        "is_volume_spike": is_spike,
        "trades_count": len(in_window),
    }


# ---------------------------------------------------------------------------
# 3. Volume Delta
# ---------------------------------------------------------------------------


def compute_volume_delta(
    trades: list[dict[str, Any]],
    *,
    window_sec: float = 60.0,
    now_ts_ms: int | None = None,
) -> dict[str, Any]:
    """
    Дельта объёмов: buy_volume - sell_volume за окно.

    trades: список сделок из TradesStream (side, size) или сырой Bybit (S, v).
    window_sec: окно в секундах.
    now_ts_ms: конец окна (мс); если None — макс T по сделкам.

    Возвращает: delta, buy_volume, sell_volume, delta_ratio (нормализованная), trades_count.
    """
    if not trades:
        return {
            "delta": 0.0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "delta_ratio": 0.0,
            "trades_count": 0,
        }
    end_ts = now_ts_ms if now_ts_ms is not None else max((t.get("T") or 0) for t in trades)
    in_window = _trades_in_window(trades, end_ts, window_sec)
    buy_vol = 0.0
    sell_vol = 0.0
    for t in in_window:
        vol, side = _volume_and_side(t)
        if "buy" in side:
            buy_vol += vol
        else:
            sell_vol += vol
    delta = buy_vol - sell_vol
    total = buy_vol + sell_vol
    delta_ratio = (delta / total) if total > 0 else 0.0
    return {
        "delta": delta,
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "delta_ratio": delta_ratio,
        "trades_count": len(in_window),
    }


def _level_price(lev: dict[str, Any]) -> float | None:
    """Цена уровня из DOM (price) или trading_zones (price)."""
    p = lev.get("price")
    if p is None:
        return None
    try:
        return float(p)
    except (TypeError, ValueError):
        return None


def _level_is_support(lev: dict[str, Any]) -> bool:
    """Уровень как поддержка (sweep низа): side=bid или type=support."""
    side = str(lev.get("side", "")).strip().lower()
    t = str(lev.get("type", "")).strip().lower()
    return side == "bid" or t == "support"


def _level_is_resistance(lev: dict[str, Any]) -> bool:
    """Уровень как сопротивление (sweep верха): side=ask или type=resistance."""
    side = str(lev.get("side", "")).strip().lower()
    t = str(lev.get("type", "")).strip().lower()
    return side == "ask" or t == "resistance"


# ---------------------------------------------------------------------------
# 4. Sweeps (сметание уровней)
# ---------------------------------------------------------------------------


def detect_sweeps(
    candles: list[dict[str, Any]],
    dom_levels: list[dict[str, Any]] | None = None,
    *,
    lookback_bars: int = 5,
    wick_ratio_min: float = 0.5,
) -> dict[str, Any]:
    """
    Обнаружение sweep'ов: цена ушла за уровень (тень свечи), затем откат.

    candles: последние свечи (open, high, low, close, start_time).
    dom_levels: значимые уровни из analyze_dom (price, side=bid/ask) или trading_zones (price, type=support/resistance).
    lookback_bars: сколько последних баров проверять.
    wick_ratio_min: минимальная доля тела свечи для учёта тени (тень >= wick_ratio_min * body).

    Возвращает: recent_sweeps_bid, recent_sweeps_ask, last_sweep_side, last_sweep_time.
    """
    recent_bid: list[dict[str, Any]] = []
    recent_ask: list[dict[str, Any]] = []
    last_side: str | None = None
    last_time: int | None = None

    if not candles or not dom_levels:
        return {
            "recent_sweeps_bid": recent_bid,
            "recent_sweeps_ask": recent_ask,
            "last_sweep_side": last_side,
            "last_sweep_time": last_time,
        }

    bars = candles[-lookback_bars:] if lookback_bars > 0 else candles
    support_levels = [float(_level_price(lev)) for lev in dom_levels if _level_price(lev) is not None and _level_is_support(lev)]
    resistance_levels = [float(_level_price(lev)) for lev in dom_levels if _level_price(lev) is not None and _level_is_resistance(lev)]

    last_ts = 0
    for c in bars:
        o = float(c.get("open", 0))
        h = float(c.get("high", 0))
        low = float(c.get("low", 0))
        cl = float(c.get("close", 0))
        start_time = int(c.get("start_time", 0))
        body = abs(cl - o) or 1e-12
        lower_wick = min(o, cl) - low
        upper_wick = h - max(o, cl)

        for level in support_levels:
            if low < level < cl and lower_wick >= wick_ratio_min * body:
                recent_bid.append({"level": level, "start_time": start_time})
                if start_time > last_ts:
                    last_ts = start_time
                    last_side = "bid"
                    last_time = start_time
        for level in resistance_levels:
            if h > level > cl and upper_wick >= wick_ratio_min * body:
                recent_ask.append({"level": level, "start_time": start_time})
                if start_time > last_ts:
                    last_ts = start_time
                    last_side = "ask"
                    last_time = start_time

    return {
        "recent_sweeps_bid": recent_bid,
        "recent_sweeps_ask": recent_ask,
        "last_sweep_side": last_side,
        "last_sweep_time": last_time,
    }


# ---------------------------------------------------------------------------
# Сводный вызов (для интеграции в бота)
# ---------------------------------------------------------------------------


def analyze_orderflow(
    orderbook_snapshot: dict[str, Any] | None = None,
    recent_trades: list[dict[str, Any]] | None = None,
    candles: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Сводный анализ Order Flow: DOM, T&S, Delta, Sweeps.

    Вызывать из bot_loop при наличии OrderbookStream (и при необходимости TradesStream).
    orderbook_snapshot: OrderbookStream.get_snapshot().
    recent_trades: TradesStream.get_recent_trades() (когда будет реализован).
    candles: последние свечи младшего ТФ для sweep по теням.

    Возвращает: dom, time_and_sales, volume_delta, sweeps.
    """
    dom_kw = {k: kwargs[k] for k in ("depth_levels", "wall_percentile") if k in kwargs}
    tns_kw = {k: kwargs[k] for k in ("window_sec", "volume_spike_mult", "now_ts_ms") if k in kwargs}
    delta_kw = {k: kwargs[k] for k in ("window_sec", "now_ts_ms") if k in kwargs}
    sweeps_kw = {k: kwargs[k] for k in ("lookback_bars", "wick_ratio_min") if k in kwargs}
    dom = analyze_dom(orderbook_snapshot or {}, **dom_kw) if orderbook_snapshot else {}
    tns = analyze_time_and_sales(recent_trades or [], **tns_kw) if recent_trades else {}
    delta = compute_volume_delta(recent_trades or [], **delta_kw) if recent_trades else {}
    sweeps = detect_sweeps(candles or [], dom.get("significant_levels"), **sweeps_kw) if candles else {}

    return {
        "dom": dom,
        "time_and_sales": tns,
        "volume_delta": delta,
        "sweeps": sweeps,
    }
