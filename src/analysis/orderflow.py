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


def last_trades_and_block(
    trades: list[dict[str, Any]],
    *,
    last_k: int = 10,
    bias_ratio_min: float = 1.2,
) -> dict[str, Any]:
    """
    Последние K сделок и «последний блок» (лента как у пропов).

    trades: список сделок (от старых к новым); берутся последние last_k.
    last_k: сколько последних сделок учитывать.
    bias_ratio_min: отношение buy/sell или sell/buy выше порога → bias buy/sell.

    Возвращает: last_trades_bias ("buy" | "sell" | "neutral"), last_block_side ("buy" | "sell" | None),
    last_trades_buy_vol, last_trades_sell_vol, last_trades_count.
    """
    if not trades or last_k <= 0:
        return {
            "last_trades_bias": "neutral",
            "last_block_side": None,
            "last_trades_buy_vol": 0.0,
            "last_trades_sell_vol": 0.0,
            "last_trades_count": 0,
        }
    last = trades[-last_k:]
    buy_vol = 0.0
    sell_vol = 0.0
    for t in last:
        vol, side = _volume_and_side(t)
        if "buy" in side:
            buy_vol += vol
        else:
            sell_vol += vol
    total = buy_vol + sell_vol
    bias = "neutral"
    if total > 0:
        if buy_vol >= bias_ratio_min * sell_vol and sell_vol > 0:
            bias = "buy"
        elif sell_vol >= bias_ratio_min * buy_vol and buy_vol > 0:
            bias = "sell"
        elif buy_vol > 0 and sell_vol == 0:
            bias = "buy"
        elif sell_vol > 0 and buy_vol == 0:
            bias = "sell"
    last_block_side = None
    if last:
        _, side = _volume_and_side(last[-1])
        last_block_side = "buy" if "buy" in side else "sell"
    return {
        "last_trades_bias": bias,
        "last_block_side": last_block_side,
        "last_trades_buy_vol": round(buy_vol, 4),
        "last_trades_sell_vol": round(sell_vol, 4),
        "last_trades_count": len(last),
    }


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


def trades_by_level(
    trades: list[dict[str, Any]],
    *,
    window_sec: float = 60.0,
    now_ts_ms: int | None = None,
    bucket_tick: float = 0.1,
    top_n: int = 10,
) -> dict[str, Any]:
    """
    Агрегация T&S по ценовым уровням: объём (buy/sell/total) на каждый бакет цены за окно.

    trades: список сделок (T, side/S, size/v, p/price).
    window_sec: окно в секундах.
    now_ts_ms: конец окна (мс); None = макс T по сделкам.
    bucket_tick: шаг цены для бакета (0.1 для BTCUSDT linear).
    top_n: сколько «горячих» уровней вернуть по убыванию total_volume.

    Возвращает: volume_by_level (список {price, buy_volume, sell_volume, total_volume}), hot_levels (топ top_n).
    """
    if not trades:
        return {"volume_by_level": [], "hot_levels": []}
    end_ts = now_ts_ms if now_ts_ms is not None else max((t.get("T") or 0) for t in trades)
    in_window = _trades_in_window(trades, end_ts, window_sec)
    buckets: dict[float, list[tuple[float, str]]] = {}
    for t in in_window:
        try:
            price = float(t.get("p") or t.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        bucket = round(price / bucket_tick) * bucket_tick
        vol, side = _volume_and_side(t)
        if bucket not in buckets:
            buckets[bucket] = []
        buckets[bucket].append((vol, side))
    volume_by_level: list[dict[str, Any]] = []
    for price_bucket, vol_sides in buckets.items():
        buy_vol = sum(v for v, s in vol_sides if "buy" in s)
        sell_vol = sum(v for v, s in vol_sides if "buy" not in s)
        total = buy_vol + sell_vol
        volume_by_level.append({
            "price": price_bucket,
            "buy_volume": round(buy_vol, 4),
            "sell_volume": round(sell_vol, 4),
            "total_volume": round(total, 4),
        })
    volume_by_level.sort(key=lambda x: x["total_volume"], reverse=True)
    hot_levels = volume_by_level[:top_n]
    return {"volume_by_level": volume_by_level, "hot_levels": hot_levels}


def compute_delta_price_divergence(
    trades: list[dict[str, Any]],
    *,
    window_sec: float = 20.0,
    now_ts_ms: int | None = None,
    delta_ratio_threshold: float = 0.1,
) -> dict[str, Any]:
    """
    Дивергенция дельты и цены за окно: цена растёт при отрицательной дельте = медвежья; цена падает при положительной = бычья.

    trades: список сделок (T, p/price, side, size/v).
    window_sec: окно в секундах.
    now_ts_ms: конец окна (мс).
    delta_ratio_threshold: порог |delta_ratio| для учёта дивергенции.

    Возвращает: bearish_divergence (price up, delta < -threshold), bullish_divergence (price down, delta > threshold),
    first_price, last_price, delta_ratio.
    """
    out: dict[str, Any] = {
        "bearish_divergence": False,
        "bullish_divergence": False,
        "first_price": None,
        "last_price": None,
        "delta_ratio": 0.0,
    }
    if not trades or window_sec <= 0:
        return out
    end_ts = now_ts_ms if now_ts_ms is not None else max((t.get("T") or 0) for t in trades)
    in_window = _trades_in_window(trades, end_ts, window_sec)
    if len(in_window) < 2:
        return out
    delta = compute_volume_delta(trades, window_sec=window_sec, now_ts_ms=end_ts)
    delta_ratio = float(delta.get("delta_ratio") or 0.0)
    out["delta_ratio"] = delta_ratio
    try:
        first_price = float(in_window[0].get("p") or in_window[0].get("price") or 0)
        last_price = float(in_window[-1].get("p") or in_window[-1].get("price") or 0)
    except (TypeError, ValueError):
        return out
    if first_price <= 0 or last_price <= 0:
        return out
    out["first_price"] = first_price
    out["last_price"] = last_price
    price_up = last_price > first_price
    price_down = last_price < first_price
    out["bearish_divergence"] = price_up and delta_ratio <= -delta_ratio_threshold
    out["bullish_divergence"] = price_down and delta_ratio >= delta_ratio_threshold
    return out


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
            "first_half_delta_ratio": 0.0,
            "second_half_delta_ratio": 0.0,
            "trades_count": 0,
        }
    end_ts = now_ts_ms if now_ts_ms is not None else max((t.get("T") or 0) for t in trades)
    in_window = _trades_in_window(trades, end_ts, window_sec)
    half_sec = window_sec / 2.0
    second_half_begin = int(end_ts - half_sec * 1000)
    first_half_trades = [t for t in in_window if (t.get("T") or 0) < second_half_begin]
    second_half_trades = [t for t in in_window if (t.get("T") or 0) >= second_half_begin]

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

    b1, s1 = 0.0, 0.0
    for t in first_half_trades:
        vol, side = _volume_and_side(t)
        if "buy" in side:
            b1 += vol
        else:
            s1 += vol
    tot1 = b1 + s1
    first_half_delta_ratio = ((b1 - s1) / tot1) if tot1 > 0 else 0.0

    b2, s2 = 0.0, 0.0
    for t in second_half_trades:
        vol, side = _volume_and_side(t)
        if "buy" in side:
            b2 += vol
        else:
            s2 += vol
    tot2 = b2 + s2
    second_half_delta_ratio = ((b2 - s2) / tot2) if tot2 > 0 else 0.0

    return {
        "delta": delta,
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "delta_ratio": delta_ratio,
        "first_half_delta_ratio": first_half_delta_ratio,
        "second_half_delta_ratio": second_half_delta_ratio,
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
# 5. Поглощение (absorption): изменение стакана до/после крупной сделки
# ---------------------------------------------------------------------------


def analyze_absorption(
    prev_snapshot: dict[str, Any] | None,
    current_snapshot: dict[str, Any],
    *,
    depth_levels: int = 20,
    min_drop_ratio: float = 0.7,
) -> dict[str, Any]:
    """
    Сравнение стакана до и после: снижение объёма на стороне спроса = поглощение.

    prev_snapshot: снимок стакана до тика (None = нет предыдущего).
    current_snapshot: текущий снимок.
    depth_levels: сколько уровней суммировать с каждой стороны.
    min_drop_ratio: порог: текущий объём < prev * min_drop_ratio считаем поглощением (0.7 = падение на 30%).

    Возвращает: absorption_bid (bool), absorption_ask (bool), bid_volume_before, bid_volume_after,
    ask_volume_before, ask_volume_after, bid_drop_ratio, ask_drop_ratio.
    """
    out: dict[str, Any] = {
        "absorption_bid": False,
        "absorption_ask": False,
        "bid_volume_before": None,
        "bid_volume_after": None,
        "ask_volume_before": None,
        "ask_volume_after": None,
        "bid_drop_ratio": None,
        "ask_drop_ratio": None,
    }
    if not current_snapshot:
        return out
    bids_curr = _parse_levels(current_snapshot, "bid", depth_levels)
    asks_curr = _parse_levels(current_snapshot, "ask", depth_levels)
    vol_bid_after = sum(s for _, s in bids_curr)
    vol_ask_after = sum(s for _, s in asks_curr)
    out["bid_volume_after"] = vol_bid_after
    out["ask_volume_after"] = vol_ask_after
    if not prev_snapshot:
        return out
    bids_prev = _parse_levels(prev_snapshot, "bid", depth_levels)
    asks_prev = _parse_levels(prev_snapshot, "ask", depth_levels)
    vol_bid_before = sum(s for _, s in bids_prev)
    vol_ask_before = sum(s for _, s in asks_prev)
    out["bid_volume_before"] = vol_bid_before
    out["ask_volume_before"] = vol_ask_before
    if vol_bid_before > 0:
        r = vol_bid_after / vol_bid_before
        out["bid_drop_ratio"] = round(r, 4)
        if r < min_drop_ratio:
            out["absorption_bid"] = True
    if vol_ask_before > 0:
        r = vol_ask_after / vol_ask_before
        out["ask_drop_ratio"] = round(r, 4)
        if r < min_drop_ratio:
            out["absorption_ask"] = True
    return out


def enrich_absorption_with_block(
    absorption: dict[str, Any] | None,
    last_trades: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Связка поглощения с последним блоком: покупатели съели ask → бычий контекст; продавцы съели bid → медвежий.

    absorption: результат analyze_absorption (absorption_bid, absorption_ask).
    last_trades: результат last_trades_and_block (last_block_side).

    Добавляет absorption_bullish (True если absorption_ask и last_block_side buy), absorption_bearish (True если absorption_bid и last_block_side sell).
    """
    if not absorption:
        return absorption
    side = (last_trades or {}).get("last_block_side")
    if not side:
        absorption["absorption_bullish"] = False
        absorption["absorption_bearish"] = False
        return absorption
    side = str(side).strip().lower()
    absorption["absorption_bullish"] = bool(
        absorption.get("absorption_ask") and "buy" in side
    )
    absorption["absorption_bearish"] = bool(
        absorption.get("absorption_bid") and "sell" in side
    )
    return absorption


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
    short_window_sec: короткое окно «последний импульс» для context_now (0 = выкл).

    Возвращает: dom, time_and_sales, volume_delta, sweeps, short_window_delta (если short_window_sec > 0).
    """
    dom_kw = {k: kwargs[k] for k in ("depth_levels", "wall_percentile") if k in kwargs}
    tns_kw = {k: kwargs[k] for k in ("window_sec", "volume_spike_mult", "now_ts_ms") if k in kwargs}
    delta_kw = {k: kwargs[k] for k in ("window_sec", "now_ts_ms") if k in kwargs}
    sweeps_kw = {k: kwargs[k] for k in ("lookback_bars", "wick_ratio_min") if k in kwargs}
    short_window_sec = float(kwargs.get("short_window_sec") or 0)
    now_ts_ms = kwargs.get("now_ts_ms")

    dom = analyze_dom(orderbook_snapshot or {}, **dom_kw) if orderbook_snapshot else {}
    tns = analyze_time_and_sales(recent_trades or [], **tns_kw) if recent_trades else {}
    delta = compute_volume_delta(recent_trades or [], **delta_kw) if recent_trades else {}
    sweeps = detect_sweeps(candles or [], dom.get("significant_levels"), **sweeps_kw) if candles else {}
    tns_level_kw = {k: kwargs[k] for k in ("window_sec", "now_ts_ms") if k in kwargs}
    trades_by_level_result = (
        trades_by_level(recent_trades or [], bucket_tick=0.1, top_n=10, **tns_level_kw)
        if recent_trades else {"volume_by_level": [], "hot_levels": []}
    )

    out: dict[str, Any] = {
        "dom": dom,
        "time_and_sales": tns,
        "volume_delta": delta,
        "sweeps": sweeps,
        "trades_by_level": trades_by_level_result,
    }
    if short_window_sec > 0 and recent_trades:
        short_delta = compute_volume_delta(
            recent_trades,
            window_sec=short_window_sec,
            now_ts_ms=now_ts_ms,
        )
        out["short_window_delta"] = short_delta
        out["delta_price_divergence"] = compute_delta_price_divergence(
            recent_trades,
            window_sec=short_window_sec,
            now_ts_ms=now_ts_ms,
            delta_ratio_threshold=0.1,
        )
    else:
        out["short_window_delta"] = None
        out["delta_price_divergence"] = None
    last_k = int(kwargs.get("last_trades_k") or 10)
    if recent_trades and last_k > 0:
        out["last_trades"] = last_trades_and_block(recent_trades, last_k=last_k)
    else:
        out["last_trades"] = None
    return out
