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


def build_candlestick_trend_chart(
    candles: list[dict[str, Any]],
    symbol: str,
    timeframe: str,
    *,
    lookback: int = 100,
    dpi: int = 120,
    figsize: tuple[float, float] = (12, 6),
) -> io.BytesIO:
    """
    Строит свечной график: свечи из БД и зоны трендов (Вверх / Вниз / Флэт) по detect_trend.

    candles: список dict с ключами start_time, open, high, low, close, volume (от старых к новым).
    symbol, timeframe — для заголовка и расчёта тренда.
    lookback: окно для detect_trend.
    Возвращает BytesIO с PNG.
    """
    if not candles or len(candles) < lookback + 1:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
        ax.text(0.5, 0.5, "Недостаточно свечей для графика", ha="center", va="center", fontsize=14)
        ax.axis("off")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
        plt.close(fig)
        buf.seek(0)
        return buf

    # Для BTC на дневном ТФ отсекаем свечи с нереалистичным движением (>50% за день) — часто биржевой мусор.
    if timeframe == "D" and "BTC" in symbol.upper():
        filtered = []
        for c in candles:
            o, cl = float(c["open"]), float(c["close"])
            if o and o > 0 and abs(cl - o) / o <= 0.5:
                filtered.append(c)
        if len(filtered) >= lookback + 1:
            candles = filtered

    n = len(candles)
    trend_ranges = _compute_trend_ranges(candles, lookback, timeframe)

    opens = np.array([c["open"] for c in candles], dtype=float)
    highs = np.array([c["high"] for c in candles], dtype=float)
    lows = np.array([c["low"] for c in candles], dtype=float)
    closes = np.array([c["close"] for c in candles], dtype=float)

    # Коррекция масштаба для BTC: в БД бывают завышенные значения (сотни тысяч / миллионы).
    # 1) Если в выборке есть цены >100k — считаем это ошибкой и масштабируем ВСЁ вниз до 0–95k.
    # 2) Иначе при двух диапазонах (старые 0–15k, новые 50k–100k) поднимаем старые к новым.
    if "BTC" in symbol.upper():
        max_high = float(np.max(highs))
        if max_high > 100_000:
            # Завышенные данные (в т.ч. миллионы) — приводим весь график к нормальному масштабу.
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

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")
    ax.grid(True, alpha=0.3, linestyle="-")
    ax.set_axisbelow(True)

    y_min_glob = float(min(lows.min(), opens.min(), closes.min()))
    y_max_glob = float(max(highs.max(), opens.max(), closes.max()))

    # Зоны трендов: Вверх (зелёный), Вниз (красный), Флэт (серый) — полупрозрачная заливка по всей высоте
    for direction in ("up", "down", "flat"):
        color = TREND_CHART_COLORS.get(direction, "#95a5a6")
        for (i0, i1) in trend_ranges.get(direction, []):
            ax.axvspan(i0 - 0.5, i1 + 0.5, facecolor=color, alpha=0.25)

    # Свечи: тело + тени
    width = 0.7
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = "#26a69a" if c >= o else "#ef5350"
        # Тень
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, solid_capstyle="round")
        # Тело
        body_bottom = min(o, c)
        body_height = abs(c - o)
        if body_height < (y_max_glob - y_min_glob) * 0.001:
            body_height = (y_max_glob - y_min_glob) * 0.001
        rect = plt.Rectangle(
            (i - width / 2, body_bottom),
            width,
            body_height,
            facecolor=color,
            edgecolor=color,
            linewidth=0.5,
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

    # Блок данных по последней свече (уже в правильном масштабе после возможной коррекции)
    last_ts = candles[-1]["start_time"]
    last_ts_sec = last_ts / 1000 if last_ts > 1e10 else last_ts
    last_date_str = datetime.utcfromtimestamp(last_ts_sec).strftime("%d.%m.%Y")
    o, h, l, c = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    change = c - o
    change_pct = (change / o * 100) if o and o != 0 else 0
    text_box = (
        f"Последняя свеча: {last_date_str}\n"
        f"ОТКР {o:,.1f}\nМАКС {h:,.1f}\nМИН {l:,.1f}\nЗАКР {c:,.1f}\n"
        f"Change {change:+,.1f} ({change_pct:+.2f}%)"
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

    # Легенда: Вверх / Вниз / Флэт
    legend_handles = [
        mpatches.Patch(color=TREND_CHART_COLORS["up"], alpha=0.25, label=TREND_NAMES_RU_CHART["up"]),
        mpatches.Patch(color=TREND_CHART_COLORS["down"], alpha=0.25, label=TREND_NAMES_RU_CHART["down"]),
        mpatches.Patch(color=TREND_CHART_COLORS["flat"], alpha=0.25, label=TREND_NAMES_RU_CHART["flat"]),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=9)

    ax.set_title(f"{symbol}  |  ТФ {timeframe}  |  Тренды (Вверх / Вниз / Флэт)  |  {n} свечей")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf
