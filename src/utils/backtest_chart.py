"""
Визуализация результатов бэктеста фаз для Telegram и отчётов.

- build_phases_chart / build_trend_chart: столбчатые графики точности по фазам/направлениям.
- build_candlestick_trend_chart: свечной график из БД с зонами трендов (Вверх / Вниз / Флэт) по detect_trend.
Возвращает PNG в BytesIO для отправки фото в Telegram.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any

# Бэкенд без GUI — для работы в потоке/без дисплея
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
import numpy as np  # noqa: E402

# Цвета свечей в стиле TradingView: зелёный — бычья (close >= open), красный — медвежья
CANDLE_COLOR_UP = "#26a67a"   # зелёный
CANDLE_COLOR_DOWN = "#ef5350"  # красный


def build_phases_chart(data: dict[str, Any], dpi: int = 120) -> io.BytesIO:
    """
    Строит график бэктеста фаз по данным из backtest_phases.run_for_chart().

    data: dict с ключами stats, phase_summary, threshold_up, threshold_down.
    Возвращает BytesIO с PNG (для send_photo в Telegram).
    """
    stats = data.get("stats") or {}
    phase_summary = data.get("phase_summary") or []
    threshold_up = data.get("threshold_up", 0.005)
    threshold_down = data.get("threshold_down", -0.005)

    if not phase_summary:
        # Пустой график с текстом
        fig, ax = plt.subplots(figsize=(8, 4), dpi=dpi)
        ax.text(0.5, 0.5, "Нет данных для графика", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        return buf

    symbol = stats.get("symbol", "—")
    timeframe = stats.get("timeframe", "—")
    total_accuracy = stats.get("total_accuracy", 0.0) * 100
    total_n = stats.get("total_n", 0)
    bull_ok, bull_total = stats.get("bull_ok", 0), stats.get("bull_total", 0)
    bear_ok, bear_total = stats.get("bear_ok", 0), stats.get("bear_total", 0)
    bars_used = data.get("bars_used")
    period_str = f", {bars_used} свечей" if bars_used is not None else ""

    labels = [p["name_ru"] for p in phase_summary]
    mean_rets = [p["mean_ret"] * 100 for p in phase_summary]
    counts = [p["count"] for p in phase_summary]
    colors = []
    for p in phase_summary:
        ph = p.get("phase", "")
        if ph in ("markup", "recovery", "capitulation"):
            colors.append("#2ecc71")  # зелёный — бычьи
        elif ph in ("markdown", "distribution"):
            colors.append("#e74c3c")  # красный — медвежьи
        else:
            colors.append("#95a5a6")  # серый — прочие

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), dpi=dpi, gridspec_kw={"height_ratios": [1.2, 1]})
    x = range(len(labels))

    # Верхний: средняя доходность по фазам (%)
    bars = ax1.bar(x, mean_rets, color=colors, edgecolor="black", linewidth=0.5)
    ax1.axhline(y=threshold_up * 100, color="green", linestyle="--", linewidth=0.8, alpha=0.7)
    ax1.axhline(y=0, color="black", linewidth=0.5)
    ax1.axhline(y=threshold_down * 100, color="red", linestyle="--", linewidth=0.8, alpha=0.7)
    ax1.set_ylabel("Средняя доходность (%)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=25, ha="right")
    ax1.set_title(f"Бэктест фаз  |  {symbol}  ТФ {timeframe}{period_str}  |  Точность: {total_accuracy:.1f}% (n={total_n})")
    ax1.grid(axis="y", alpha=0.3)
    for i, (bar, val) in enumerate(zip(bars, mean_rets)):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + (0.2 if val >= 0 else -0.4), f"{val:.1f}%", ha="center", va="bottom" if val >= 0 else "top", fontsize=8, fontweight="bold")

    # Нижний: количество наблюдений по фазам
    ax2.bar(x, counts, color=colors, edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Кол-во наблюдений")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=25, ha="right")
    ax2.grid(axis="y", alpha=0.3)

    # Легенда
    bull_patch = mpatches.Patch(color="#2ecc71", label=f"Бычьи: {bull_ok}/{bull_total}")
    bear_patch = mpatches.Patch(color="#e74c3c", label=f"Медвежьи: {bear_ok}/{bear_total}")
    ax1.legend(handles=[bull_patch, bear_patch], loc="upper right", fontsize=8)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_trend_chart(data: dict[str, Any], dpi: int = 120) -> io.BytesIO:
    """
    Строит график бэктеста тренда по данным из backtest_trend.run_for_chart().

    data: dict с ключами stats, direction_summary, threshold_up, threshold_down.
    Возвращает BytesIO с PNG (для send_photo в Telegram).
    """
    stats = data.get("stats") or {}
    direction_summary = data.get("direction_summary") or []
    threshold_up = data.get("threshold_up", 0.005)
    threshold_down = data.get("threshold_down", -0.005)

    if not direction_summary:
        fig, ax = plt.subplots(figsize=(8, 4), dpi=dpi)
        ax.text(0.5, 0.5, "Нет данных для графика", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        return buf

    symbol = stats.get("symbol", "—")
    timeframe = stats.get("timeframe", "—")
    total_accuracy = stats.get("total_accuracy", 0.0) * 100
    total_n = stats.get("total_n", 0)
    up_ok, up_total = stats.get("up_ok", 0), stats.get("up_total", 0)
    down_ok, down_total = stats.get("down_ok", 0), stats.get("down_total", 0)
    flat_count = stats.get("flat_count", 0)
    bars_used = data.get("bars_used")
    period_str = f", {bars_used} свечей" if bars_used is not None else ""

    labels = [d["name_ru"] for d in direction_summary]
    mean_rets = [d["mean_ret"] * 100 for d in direction_summary]
    counts = [d["count"] for d in direction_summary]
    colors = []
    for d in direction_summary:
        dr = d.get("direction", "")
        if dr == "up":
            colors.append("#2ecc71")
        elif dr == "down":
            colors.append("#e74c3c")
        else:
            colors.append("#95a5a6")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), dpi=dpi, gridspec_kw={"height_ratios": [1.2, 1]})
    x = range(len(labels))

    bars = ax1.bar(x, mean_rets, color=colors, edgecolor="black", linewidth=0.5)
    ax1.axhline(y=threshold_up * 100, color="green", linestyle="--", linewidth=0.8, alpha=0.7)
    ax1.axhline(y=0, color="black", linewidth=0.5)
    ax1.axhline(y=threshold_down * 100, color="red", linestyle="--", linewidth=0.8, alpha=0.7)
    ax1.set_ylabel("Средняя доходность (%)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=25, ha="right")
    ax1.set_title(f"Бэктест тренда  |  {symbol}  ТФ {timeframe}{period_str}  |  Точность: {total_accuracy:.1f}% (n={total_n}), flat: {flat_count}")
    ax1.grid(axis="y", alpha=0.3)
    for bar, val in zip(bars, mean_rets):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + (0.2 if val >= 0 else -0.4), f"{val:.1f}%", ha="center", va="bottom" if val >= 0 else "top", fontsize=8, fontweight="bold")

    ax2.bar(x, counts, color=colors, edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Кол-во наблюдений")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=25, ha="right")
    ax2.grid(axis="y", alpha=0.3)

    up_patch = mpatches.Patch(color="#2ecc71", label=f"Вверх: {up_ok}/{up_total}")
    down_patch = mpatches.Patch(color="#e74c3c", label=f"Вниз: {down_ok}/{down_total}")
    ax1.legend(handles=[up_patch, down_patch], loc="upper right", fontsize=8)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf


# Цвета трендов на свечном графике: Вверх / Вниз / Флэт
TREND_CHART_COLORS = {
    "up": "#2ecc71",    # зелёный — тренд вверх
    "down": "#e74c3c",  # красный — тренд вниз
    "flat": "#95a5a6",  # серый — флэт
}

TREND_NAMES_RU_CHART = {"up": "Вверх", "down": "Вниз", "flat": "Флэт"}


def _compute_trend_ranges(
    candles: list[dict[str, Any]],
    lookback: int,
    timeframe: str,
) -> dict[str, list[tuple[int, int]]]:
    """
    Для каждого бара (начиная с lookback) считает тренд (detect_trend).
    Возвращает trend_ranges: "up"|"down"|"flat" -> [(start_idx, end_idx), ...].
    """
    from ..analysis.market_trend import detect_trend

    n = len(candles)
    trend_ranges: dict[str, list[tuple[int, int]]] = {"up": [], "down": [], "flat": []}

    for i in range(lookback, n):
        window = candles[i - lookback : i]
        try:
            tr = detect_trend(window, timeframe=timeframe)
            trend = tr.get("direction", "flat")
        except Exception:
            trend = "flat"
        r = trend_ranges[trend]
        if r and r[-1][1] == i - 1:
            r[-1] = (r[-1][0], i)
        else:
            r.append((i, i))

    return trend_ranges


def _shift_trend_ranges(
    trend_ranges: dict[str, list[tuple[int, int]]],
    offset: int,
    length: int,
) -> dict[str, list[tuple[int, int]]]:
    """Сдвигает индексы диапазонов на -offset и обрезает по [0, length)."""
    out: dict[str, list[tuple[int, int]]] = {"up": [], "down": [], "flat": []}
    for direction in ("up", "down", "flat"):
        for i0, i1 in trend_ranges.get(direction, []):
            j0 = max(0, i0 - offset)
            j1 = min(length, i1 - offset)
            if j0 < j1:
                out[direction].append((j0, j1))
    return out


def build_daily_trend_full_chart(
    candles: list[dict[str, Any]],
    symbol: str,
    *,
    lookback: int = 100,
    max_candles_display: int = 2000,
    dpi: int = 120,
    figsize: tuple[float, float] = (14, 7),
) -> io.BytesIO:
    """
    Тренд по всей БД на таймфрейме D: загрузи все D-свечи, посчитай тренд на полной истории,
    отобрази последние max_candles_display свечей с зонами Вверх/Вниз/Флэт.

    candles: все дневные свечи (от старых к новым), без лимита.
    symbol: пара для заголовка и фильтра цен (BTC).
    lookback: окно для detect_trend.
    max_candles_display: сколько последних свечей рисовать (остальное — тренд считается по полной истории).
    Возвращает BytesIO с PNG.
    """
    timeframe = "D"
    min_candles = lookback + 1
    if not candles or len(candles) < min_candles:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
        ax.text(0.5, 0.5, "Недостаточно свечей для графика тренда (нужно минимум %s)" % min_candles, ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        return buf

    # Фильтр цен (BTC 1k–150k, макс. 30% диапазон)
    if "BTC" in symbol.upper():
        price_lo, price_hi = 1_000.0, 150_000.0
        max_range_ratio = 0.30
        filtered = []
        for c in candles:
            o = float(c.get("open", 0) or 0)
            h = float(c.get("high", 0) or 0)
            l_ = float(c.get("low", 0) or 0)
            cl = float(c.get("close", 0) or 0)
            if o <= 0:
                continue
            mn, mx = min(o, h, l_, cl), max(o, h, l_, cl)
            if mn < price_lo or mx > price_hi:
                continue
            if (h - l_) / o > max_range_ratio:
                continue
            filtered.append(c)
        if len(filtered) >= min_candles:
            candles = filtered

    n_full = len(candles)
    trend_ranges_full = _compute_trend_ranges(candles, lookback, timeframe)
    display_n = min(n_full, max_candles_display)
    display_candles = candles[-display_n:]
    offset = n_full - display_n
    trend_ranges = _shift_trend_ranges(trend_ranges_full, offset, display_n) if offset > 0 else trend_ranges_full
    n = len(display_candles)

    opens = np.array([c["open"] for c in display_candles], dtype=float)
    highs = np.array([c["high"] for c in display_candles], dtype=float)
    lows = np.array([c["low"] for c in display_candles], dtype=float)
    closes = np.array([c["close"] for c in display_candles], dtype=float)

    fig_w = min(28.0, max(figsize[0], 12.0 + n * 0.012))
    fig_h = figsize[1]
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")
    ax.grid(True, alpha=0.3, linestyle="-")
    ax.set_axisbelow(True)

    y_min_glob = float(min(lows.min(), opens.min(), closes.min()))
    y_max_glob = float(max(highs.max(), opens.max(), closes.max()))

    for direction in ("up", "down", "flat"):
        color = TREND_CHART_COLORS.get(direction, "#95a5a6")
        for (i0, i1) in trend_ranges.get(direction, []):
            ax.axvspan(i0 - 0.5, i1 + 0.5, facecolor=color, alpha=0.25)

    min_body_height = (y_max_glob - y_min_glob) * 0.0005
    width = min(0.85, 0.5 + 300.0 / max(n, 1))
    wick_lw = 1.0
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = CANDLE_COLOR_UP if c >= o else CANDLE_COLOR_DOWN
        body_bottom = min(o, c)
        body_top_real = max(o, c)
        body_height_real = body_top_real - body_bottom
        body_height_draw = max(body_height_real, min_body_height)
        body_top_draw = body_bottom + body_height_draw
        if l < body_bottom - 1e-9:
            ax.plot([i, i], [l, body_bottom], color=color, linewidth=wick_lw, solid_capstyle="round")
        if h > body_top_draw + 1e-9:
            ax.plot([i, i], [body_top_draw, h], color=color, linewidth=wick_lw, solid_capstyle="round")
        rect = plt.Rectangle(
            (i - width / 2, body_bottom),
            width,
            body_height_draw,
            facecolor=color,
            edgecolor=color,
            linewidth=0.6,
        )
        ax.add_patch(rect)

    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(y_min_glob - (y_max_glob - y_min_glob) * 0.01, y_max_glob + (y_max_glob - y_min_glob) * 0.01)
    ax.set_ylabel("Цена (USDT)")
    ax.set_xlabel("Дата")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))

    step_ticks = max(1, n // 12)
    tick_indices = list(range(0, n, step_ticks))
    if n - 1 not in tick_indices:
        tick_indices.append(n - 1)
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(
        [
            datetime.utcfromtimestamp(display_candles[i]["start_time"] / 1000).strftime("%b %Y")
            if display_candles[i]["start_time"] > 1e10
            else datetime.utcfromtimestamp(display_candles[i]["start_time"]).strftime("%b %Y")
            for i in tick_indices
        ],
        rotation=25,
        ha="right",
    )

    last_ts = display_candles[-1]["start_time"]
    last_ts_sec = last_ts / 1000 if last_ts > 1e10 else last_ts
    last_date_str = datetime.utcfromtimestamp(last_ts_sec).strftime("%d.%m.%Y")
    o, h, l, c = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    change = c - o
    change_pct = (change / o * 100) if o and o != 0 else 0
    text_box = (
        f"Последняя свеча: {last_date_str}\n"
        f"ОТКР {o:,.1f}  МАКС {h:,.1f}\nМИН {l:,.1f}  ЗАКР {c:,.1f}\n"
        f"Change {change:+,.1f} ({change_pct:+.2f}%)\n"
        f"Диапазон: {y_min_glob:,.0f} – {y_max_glob:,.0f}"
    )
    ax.text(
        0.02, 0.98, text_box,
        transform=ax.transAxes, fontsize=9, verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9), family="monospace",
    )

    legend_handles = [
        mpatches.Patch(color=TREND_CHART_COLORS["up"], alpha=0.25, label=TREND_NAMES_RU_CHART["up"]),
        mpatches.Patch(color=TREND_CHART_COLORS["down"], alpha=0.25, label=TREND_NAMES_RU_CHART["down"]),
        mpatches.Patch(color=TREND_CHART_COLORS["flat"], alpha=0.25, label=TREND_NAMES_RU_CHART["flat"]),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=9)

    title_n = f"последние {n} из {n_full} свечей (тренд по всей БД)" if n_full > n else f"{n} свечей, тренд по всей БД"
    ax.set_title(f"{symbol}  |  ТФ {timeframe}  |  {title_n}  |  Вверх / Вниз / Флэт")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_candlestick_trend_chart(
    candles: list[dict[str, Any]],
    symbol: str,
    timeframe: str,
    *,
    lookback: int = 100,
    show_trends: bool = False,
    scale_correction: bool = False,
    max_candles_display: int = 730,
    dpi: int = 120,
    figsize: tuple[float, float] = (12, 6),
) -> io.BytesIO:
    """
    Строит свечной график из БД. Опционально — фоновые зоны трендов (Вверх / Вниз / Флэт) по detect_trend.

    candles: список dict с ключами start_time, open, high, low, close, volume (от старых к новым).
    symbol, timeframe — для заголовка и (при show_trends) расчёта тренда.
    lookback: окно для detect_trend (используется только при show_trends=True).
    show_trends: если False — рисуются только свечи (без фоновых зон тренда).
    scale_correction: если False — ось цены как в данных (как в TradingView). True — старая коррекция для BTC.
    max_candles_display: максимум свечей на графике (по умолчанию 730 — последние 2 года на ТФ D).
    Возвращает BytesIO с PNG.
    """
    min_candles = (lookback + 1) if show_trends else 2
    if not candles or len(candles) < min_candles:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
        ax.text(0.5, 0.5, "Недостаточно свечей для графика", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        return buf

    # Отсекаем свечи с мусором: цены вне 1k–150k и абсурдный диапазон (low/high далеко от тела).
    # (high-low)/open > 30% для дневных — нереалистично; отсекает «длинные тени» с неверным low/high.
    if "BTC" in symbol.upper():
        price_lo, price_hi = 1_000.0, 150_000.0  # USDT для BTC
        max_range_ratio = 0.30  # макс. (high-low)/open
        filtered = []
        for c in candles:
            o = float(c.get("open", 0) or 0)
            h = float(c.get("high", 0) or 0)
            l_ = float(c.get("low", 0) or 0)
            cl = float(c.get("close", 0) or 0)
            if o <= 0:
                continue
            mn, mx = min(o, h, l_, cl), max(o, h, l_, cl)
            if mn < price_lo or mx > price_hi:
                continue
            if (h - l_) / o > max_range_ratio:
                continue
            filtered.append(c)
        if len(filtered) >= min_candles:
            candles = filtered

    # Жёстко: только последние 730 дней от последней свечи (ровно 2 года на ТФ D).
    if candles:
        last_ts_ms = candles[-1]["start_time"] if candles[-1]["start_time"] > 1e10 else candles[-1]["start_time"] * 1000
        cutoff_ts_ms = last_ts_ms - 730 * 24 * 3600 * 1000
        candles = [c for c in candles if (c["start_time"] if c["start_time"] > 1e10 else c["start_time"] * 1000) >= cutoff_ts_ms]

    n_total = len(candles)
    # Ограничиваем число свечей на графике (макс. max_candles_display).
    if n_total > max_candles_display:
        candles = candles[-max_candles_display:]
    n = len(candles)
    trend_ranges = _compute_trend_ranges(candles, lookback, timeframe) if show_trends else {}

    opens = np.array([c["open"] for c in candles], dtype=float)
    highs = np.array([c["high"] for c in candles], dtype=float)
    lows = np.array([c["low"] for c in candles], dtype=float)
    closes = np.array([c["close"] for c in candles], dtype=float)

    # Коррекция масштаба для BTC только при scale_correction=True (по умолчанию — реальные цены, как в TradingView).
    if scale_correction and "BTC" in symbol.upper():
        max_high = float(np.max(highs))
        if max_high > 100_000:
            scale = max_high / 95_000.0
            opens = opens / scale
            highs = highs / scale
            lows = lows / scale
            closes = closes / scale
        else:
            low_band = (highs < 15_000) & (highs > 0)
            high_band = highs > 50_000
            if np.any(low_band) and np.any(high_band):
                ref_high = float(np.median(highs[high_band]))
                med_low = float(np.median(highs[low_band]))
                if med_low > 0 and 0 < ref_high <= 100_000:
                    scale_low = ref_high / med_low
                    opens = np.where(low_band, opens * scale_low, opens)
                    highs = np.where(low_band, highs * scale_low, highs)
                    lows = np.where(low_band, lows * scale_low, lows)
                    closes = np.where(low_band, closes * scale_low, closes)

    # Ширина графика: при большом числе свечей увеличиваем, чтобы тела были видны (как в TradingView)
    fig_w = min(24.0, max(figsize[0], 12.0 + n * 0.015))
    fig_h = figsize[1]
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")
    ax.grid(True, alpha=0.3, linestyle="-")
    ax.set_axisbelow(True)

    y_min_glob = float(min(lows.min(), opens.min(), closes.min()))
    y_max_glob = float(max(highs.max(), opens.max(), closes.max()))

    # Зоны трендов (только при show_trends): Вверх (зелёный), Вниз (красный), Флэт (серый)
    if show_trends:
        for direction in ("up", "down", "flat"):
            color = TREND_CHART_COLORS.get(direction, "#95a5a6")
            for (i0, i1) in trend_ranges.get(direction, []):
                ax.axvspan(i0 - 0.5, i1 + 0.5, facecolor=color, alpha=0.25)

    # Свечи в стиле TradingView: тело (open–close) + нижняя тень (low–min) + верхняя тень (max–high).
    # Для дожи (open==close) тело рисуем с минимальной высотой, верхняя тень начинается от верха тела.
    min_body_height = (y_max_glob - y_min_glob) * 0.0005
    width = min(0.85, 0.5 + 300.0 / max(n, 1))
    wick_lw = 1.0
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = CANDLE_COLOR_UP if c >= o else CANDLE_COLOR_DOWN
        body_bottom = min(o, c)
        body_top_real = max(o, c)
        body_height_real = body_top_real - body_bottom
        # Высота тела для отрисовки: не меньше min_body_height (чтобы дожи был виден)
        body_height_draw = max(body_height_real, min_body_height)
        body_top_draw = body_bottom + body_height_draw
        # Нижняя тень: от low до низа тела
        if l < body_bottom - 1e-9:
            ax.plot([i, i], [l, body_bottom], color=color, linewidth=wick_lw, solid_capstyle="round")
        # Верхняя тень: от верха тела (рисованного) до high
        if h > body_top_draw + 1e-9:
            ax.plot([i, i], [body_top_draw, h], color=color, linewidth=wick_lw, solid_capstyle="round")
        # Тело свечи: прямоугольник от body_bottom до body_top_draw
        rect = plt.Rectangle(
            (i - width / 2, body_bottom),
            width,
            body_height_draw,
            facecolor=color,
            edgecolor=color,
            linewidth=0.6,
        )
        ax.add_patch(rect)

    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(y_min_glob - (y_max_glob - y_min_glob) * 0.01, y_max_glob + (y_max_glob - y_min_glob) * 0.01)
    ax.set_ylabel("Цена (USDT)")
    ax.set_xlabel("Дата")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))

    # Подписи оси X — даты (каждая N-я свеча)
    step_ticks = max(1, n // 12)
    tick_indices = list(range(0, n, step_ticks))
    if n - 1 not in tick_indices:
        tick_indices.append(n - 1)
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(
        [
            datetime.utcfromtimestamp(candles[i]["start_time"] / 1000).strftime("%b %Y")
            if candles[i]["start_time"] > 1e10
            else datetime.utcfromtimestamp(candles[i]["start_time"]).strftime("%b %Y")
            for i in tick_indices
        ],
        rotation=25,
        ha="right",
    )

    # Блок данных по последней свече и диапазон цен на графике (для сверки с TradingView)
    last_ts = candles[-1]["start_time"]
    last_ts_sec = last_ts / 1000 if last_ts > 1e10 else last_ts
    last_date_str = datetime.utcfromtimestamp(last_ts_sec).strftime("%d.%m.%Y")
    o, h, l, c = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    change = c - o
    change_pct = (change / o * 100) if o and o != 0 else 0
    text_box = (
        f"Последняя свеча: {last_date_str}\n"
        f"ОТКР {o:,.1f}  МАКС {h:,.1f}\nМИН {l:,.1f}  ЗАКР {c:,.1f}\n"
        f"Change {change:+,.1f} ({change_pct:+.2f}%)\n"
        f"Диапазон на графике: {y_min_glob:,.0f} – {y_max_glob:,.0f}"
    )
    ax.text(
        0.02,
        0.98,
        text_box,
        transform=ax.transAxes,
        fontsize=9,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9),
        family="monospace",
    )

    if show_trends:
        legend_handles = [
            mpatches.Patch(color=TREND_CHART_COLORS["up"], alpha=0.25, label=TREND_NAMES_RU_CHART["up"]),
            mpatches.Patch(color=TREND_CHART_COLORS["down"], alpha=0.25, label=TREND_NAMES_RU_CHART["down"]),
            mpatches.Patch(color=TREND_CHART_COLORS["flat"], alpha=0.25, label=TREND_NAMES_RU_CHART["flat"]),
        ]
        ax.legend(handles=legend_handles, loc="upper right", fontsize=9)

    title_n = f"последние {n} из {n_total} свечей" if n_total > n else f"{n} свечей"
    ax.set_title(f"{symbol}  |  ТФ {timeframe}  |  {title_n}" + ("  |  Тренды (Вверх / Вниз / Флэт)" if show_trends else ""))
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf
