"""
Песочница торговли по микроструктуре: виртуальная позиция и PnL по сигналу microstructure_signal.

Не исполняет реальные ордера. Стартовый баланс в USD; при открытии notional = margin * leverage,
margin = equity * margin_fraction. Адаптивное плечо: от уверенности сигнала и просадки от пика
(при просадке выше SANDBOX_DRAWDOWN_LEVERAGE_PCT макс. плечо снижается вдвое). Ликвидация при
убытке >= margin_used * SANDBOX_LIQUIDATION_MAINTENANCE. Учитывается комиссия (SANDBOX_TAKER_FEE).
Сделки пишутся в logs/sandbox_trades.csv; при выключении — сводка в logs/sandbox_result.txt.
Запуск: ORDERFLOW_ENABLED=1 и MICROSTRUCTURE_SANDBOX_ENABLED=1.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Заголовки CSV лога сделок
TRADES_CSV_HEADERS = [
    "ts_utc",
    "ts_unix",
    "action",
    "side",
    "price",
    "size",
    "notional_usd",
    "commission_usd",
    "realized_pnl_usd",
    "signal_direction",
    "signal_confidence",
    "reason",
    "leverage",
    "exit_reason",   # для close: stop_loss, breakeven, take_profit, take_profit_part, trailing_stop, microstructure, liquidation
    "entry_type",    # для open: microstructure, context_now_only, context_now_primary
]

# Заголовки лога пропущенных входов (фильтры)
SKIPS_CSV_HEADERS = ["ts_utc", "ts_unix", "direction", "confidence", "skip_reason"]


def _classify_exit_reason(close_reason: str) -> str:
    """Нормализованная причина выхода для аналитики."""
    r = (close_reason or "").strip().lower()
    if "stop_loss" in r:
        return "stop_loss"
    if "breakeven" in r:
        return "breakeven"
    if "trailing_stop" in r:
        return "trailing_stop"
    if "take_profit_part" in r:
        return "take_profit_part"
    if "take_profit" in r:
        return "take_profit"
    if "liquidation" in r:
        return "liquidation"
    return "microstructure"


def _mid_from_snapshot(snapshot: dict[str, Any]) -> float | None:
    """Цена mid из снимка стакана: (best_bid + best_ask) / 2."""
    bids = snapshot.get("bids") or []
    asks = snapshot.get("asks") or []
    if not bids or not asks:
        return None
    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        return (best_bid + best_ask) / 2.0
    except (IndexError, TypeError, ValueError):
        return None


def _price_near_hot_resistance(price: float, of_result: dict[str, Any], distance_pct: float = 0.002) -> bool:
    """True если цена в пределах distance_pct от «горячего» уровня сверху (сопротивление по объёму)."""
    if price <= 0 or distance_pct <= 0:
        return False
    tbl = of_result.get("trades_by_level") or {}
    hot = tbl.get("hot_levels") or []
    for lev in hot:
        try:
            p = float(lev.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p > price and (p - price) / price <= distance_pct:
            return True
    return False


def _price_near_hot_support(price: float, of_result: dict[str, Any], distance_pct: float = 0.002) -> bool:
    """True если цена в пределах distance_pct от «горячего» уровня снизу (поддержка по объёму)."""
    if price <= 0 or distance_pct <= 0:
        return False
    tbl = of_result.get("trades_by_level") or {}
    hot = tbl.get("hot_levels") or []
    for lev in hot:
        try:
            p = float(lev.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p < price and (price - p) / price <= distance_pct:
            return True
    return False


def _get_trades_log_path() -> Path:
    """Путь к файлу лога сделок песочницы (logs/sandbox_trades.csv)."""
    from ..core import config
    log_dir = getattr(config, "LOG_DIR", None)
    if log_dir is None:
        log_dir = Path(__file__).resolve().parents[2] / "logs"
    if isinstance(log_dir, str):
        log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "sandbox_trades.csv"


def _get_skips_log_path() -> Path:
    """Путь к файлу лога пропущенных входов (logs/sandbox_skips.csv)."""
    from ..core import config
    log_dir = getattr(config, "LOG_DIR", None)
    if log_dir is None:
        log_dir = Path(__file__).resolve().parents[2] / "logs"
    if isinstance(log_dir, str):
        log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "sandbox_skips.csv"


def _archive_sandbox_csv_logs() -> None:
    """
    Архивирует текущие sandbox_trades.csv и sandbox_skips.csv перед новым прогоном,
    чтобы не смешивать данные от разных сессий/бэктестов.
    """
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path in (_get_trades_log_path(), _get_skips_log_path()):
        if path.exists() and path.stat().st_size > 0:
            archive = path.parent / (path.stem + f"_archive_{suffix}" + path.suffix)
            try:
                path.rename(archive)
                logger.info("Архив лога песочницы: %s → %s", path.name, archive.name)
            except OSError as e:
                logger.warning("Не удалось архивировать %s: %s", path, e)


def _append_trade_row(path: Path, row: dict[str, Any]) -> None:
    """Добавляет одну сделку в CSV (создаёт файл с заголовками при первом вызове)."""
    try:
        file_exists = path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=TRADES_CSV_HEADERS)
            if not file_exists:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in TRADES_CSV_HEADERS})
    except Exception as e:
        logger.warning("Не удалось записать сделку в %s: %s", path, e)


def _append_skip_row(path: Path, row: dict[str, Any]) -> None:
    """Добавляет одну запись о пропуске входа в CSV."""
    try:
        file_exists = path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SKIPS_CSV_HEADERS)
            if not file_exists:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in SKIPS_CSV_HEADERS})
    except Exception as e:
        logger.warning("Не удалось записать пропуск в %s: %s", path, e)


class MicrostructureSandbox:
    """
    Виртуальная позиция и PnL в USD по сигналу микроструктуры (long/short/none).
    Учитывается комиссия биржи (taker_fee). Каждый вход/выход логируется в CSV и в список trades.
    """

    def __init__(
        self,
        *,
        initial_balance: float = 100.0,
        min_confidence_to_open: float = 0.0,
        taker_fee: float = 0.0006,
        cooldown_sec: int = 0,
        min_hold_sec: int = 0,
        exit_none_ticks: int = 1,
        exit_min_confidence: float = 0.0,
        min_confirming_ticks: int = 0,
        exit_window_ticks: int = 0,
        exit_window_need: int = 0,
        stop_loss_pct: float = 0.0,
        breakeven_trigger_pct: float = 0.0,
        take_profit_pct: float = 0.0,
        take_profit_levels: list[tuple[float, float]] | None = None,
        trail_trigger_pct: float = 0.0,
        trail_pct: float = 0.0,
        trend_filter: bool = False,
        leverage_min: float = 1.0,
        leverage_max: float = 5.0,
        adaptive_leverage: bool = True,
        margin_fraction: float = 0.95,
        liquidation_maintenance: float = 1.0,
        drawdown_leverage_pct: float = 10.0,
        min_profit_pct: float = 0.0,
        no_open_same_tick_as_close: bool = True,
        no_open_sweep_only: bool = True,
        sweep_delay_sec: int = 0,
        use_context_now_primary: bool = False,
        use_context_now_only: bool = False,
        run_id: str | None = None,
    ):
        self.run_id = run_id  # при заданном — сделки/пропуски пишутся ещё и в БД (sandbox_trades/sandbox_skips)
        self.initial_balance = initial_balance
        self.min_confidence_to_open = min_confidence_to_open
        self.taker_fee = max(0.0, float(taker_fee))
        self.cooldown_sec = max(0, int(cooldown_sec))
        self.min_hold_sec = max(0, int(min_hold_sec))
        self.exit_none_ticks = max(1, int(exit_none_ticks))  # тиков подряд none/против для выхода
        self.exit_min_confidence = max(0.0, float(exit_min_confidence))  # выход при confidence ниже (трейлинг по микроструктуре)
        self.min_confirming_ticks = max(0, int(min_confirming_ticks))  # минимум тиков «в нашу сторону» перед разрешением выхода
        self.exit_window_ticks = max(0, int(exit_window_ticks))  # окно: последние M тиков
        self.exit_window_need = max(0, int(exit_window_need))  # сколько из M должны быть «на выход»
        self.stop_loss_pct = max(0.0, float(stop_loss_pct))  # стоп-лосс в % (0 = выкл)
        self.breakeven_trigger_pct = max(0.0, float(breakeven_trigger_pct))  # при прибыли >= этого % перенести SL в безубыток (0 = выкл)
        self.take_profit_pct = max(0.0, float(take_profit_pct))  # тейк-профит в % (0 = выкл при пустых уровнях)
        self.take_profit_levels: list[tuple[float, float]] = list(take_profit_levels) if take_profit_levels else []  # [(pct, cumulative_share), ...]
        self.trail_trigger_pct = max(0.0, float(trail_trigger_pct))  # при прибыли >= этого % включить трейлинг (0 = выкл)
        self.trail_pct = max(0.0, float(trail_pct))  # откат от пика прибыли в % — закрыть по трейлингу (0 = выкл)
        self.trend_filter = bool(trend_filter)  # не открывать против тренда старшего ТФ
        self.leverage_min = max(1.0, float(leverage_min))
        self.leverage_max = max(self.leverage_min, float(leverage_max))
        self.adaptive_leverage = bool(adaptive_leverage)
        self.margin_fraction = max(0.01, min(1.0, float(margin_fraction)))
        self.liquidation_maintenance = max(0.0, float(liquidation_maintenance))
        self.drawdown_leverage_pct = max(0.0, float(drawdown_leverage_pct))
        self.min_profit_pct = max(0.0, float(min_profit_pct))  # не закрывать по микроструктуре в плюсе, пока профит < этого %
        self.no_open_same_tick_as_close = bool(no_open_same_tick_as_close)
        self.no_open_sweep_only = bool(no_open_sweep_only)
        self.sweep_delay_sec = max(0, int(sweep_delay_sec))
        self.use_context_now_primary = bool(use_context_now_primary)
        self.use_context_now_only = bool(use_context_now_only)
        self.last_close_ts: int = 0
        self._closed_this_tick: bool = False
        self._exit_signal_ticks: int = 0  # подряд тиков с сигналом на выход
        self._confirming_ticks: int = 0  # тиков «в нашу сторону» с момента входа
        self._exit_window: list[bool] = []  # последние M флагов «хочу выйти» (для окна подтверждения)
        self._peak_equity: float = 0.0
        self._margin_used: float = 0.0
        self._current_leverage: float = 1.0
        self.position: int = 0
        self.entry_price: float = 0.0
        self.size: float = 0.0
        self.entry_ts: int = 0
        self._initial_size: float = 0.0  # размер при входе (для частичного TP)
        self._tp_closed_share: float = 0.0  # доля 0..1 уже закрыта по частичному TP
        self._sl_at_breakeven: bool = False  # True = стоп уже перенесён в безубыток по этой позиции
        self._trail_peak_pct: float = 0.0  # пик прибыли % с момента активации трейлинга; 0 = трейлинг ещё не включён
        self.total_realized_pnl: float = 0.0  # gross (до вычета комиссий)
        self.total_commission: float = 0.0
        self.last_signal: dict[str, Any] = {}
        self.last_ts: int = 0
        self.trades: list[dict[str, Any]] = []  # все сделки для сводки
        _archive_sandbox_csv_logs()

    def _compute_leverage(self, confidence: float, equity: float) -> float:
        """Адаптивное плечо: от уверенности сигнала и просадки от пика эквити."""
        if not self.adaptive_leverage or self.leverage_max <= self.leverage_min:
            return self.leverage_max
        self._peak_equity = max(self._peak_equity, equity)
        peak = self._peak_equity
        drawdown_pct = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        lev = self.leverage_min + (self.leverage_max - self.leverage_min) * confidence
        if self.drawdown_leverage_pct > 0 and drawdown_pct >= self.drawdown_leverage_pct:
            lev = min(lev, self.leverage_min + 0.5 * (self.leverage_max - self.leverage_min))
        return max(self.leverage_min, min(self.leverage_max, lev))

    def get_state(self) -> dict[str, Any]:
        """Текущее состояние песочницы (позиция, PnL в USD с учётом комиссий, счётчики)."""
        return {
            "position": self.position,
            "position_side": "flat" if self.position == 0 else ("long" if self.position == 1 else "short"),
            "entry_price": self.entry_price,
            "entry_ts": self.entry_ts,
            "size": round(self.size, 6),
            "leverage": round(self._current_leverage, 2),
            "margin_used": round(self._margin_used, 4),
            "peak_equity": round(self._peak_equity, 4),
            "initial_balance_usd": self.initial_balance,
            "total_realized_pnl": round(self.total_realized_pnl, 4),
            "total_commission": round(self.total_commission, 4),
            "trades_count": len(self.trades),
            "last_signal_direction": self.last_signal.get("direction", "—"),
            "last_signal_confidence": self.last_signal.get("confidence", 0.0),
            "last_ts": self.last_ts,
        }

    def unrealized_pnl(self, current_price: float) -> float:
        """Нереализованный PnL в USD по текущей цене (без комиссии)."""
        if self.position == 0 or self.size <= 0:
            return 0.0
        if self.position == 1:
            return (current_price - self.entry_price) * self.size
        return (self.entry_price - current_price) * self.size

    def equity(self, current_price: float) -> float:
        """Текущий эквити в USD: начальный баланс + реализованный PnL − комиссии + нереализованный PnL."""
        return self.initial_balance + self.total_realized_pnl - self.total_commission + self.unrealized_pnl(current_price)

    def _log_trade(
        self,
        ts_sec: int,
        action: str,
        side: str,
        price: float,
        size: float,
        notional_usd: float,
        commission_usd: float,
        realized_pnl_usd: float | None,
        signal_direction: str,
        signal_confidence: float,
        reason: str,
        leverage: float = 1.0,
        *,
        exit_reason: str = "",
        entry_type: str = "",
    ) -> None:
        from datetime import datetime
        row = {
            "ts_utc": datetime.utcfromtimestamp(ts_sec).strftime("%Y-%m-%d %H:%M:%S"),
            "ts_unix": ts_sec,
            "action": action,
            "side": side,
            "price": round(price, 2),
            "size": round(size, 6),
            "notional_usd": round(notional_usd, 2),
            "commission_usd": round(commission_usd, 4),
            "realized_pnl_usd": round(realized_pnl_usd, 4) if realized_pnl_usd is not None else "",
            "signal_direction": signal_direction,
            "signal_confidence": round(signal_confidence, 4),
            "reason": (reason or "")[:200],
            "leverage": round(leverage, 2) if leverage != 1.0 else "",
            "exit_reason": exit_reason,
            "entry_type": entry_type,
        }
        self.trades.append(row)
        _append_trade_row(_get_trades_log_path(), row)
        if self.run_id:
            try:
                from ..core.database import get_connection, insert_sandbox_trade
                conn = get_connection()
                cur = conn.cursor()
                insert_sandbox_trade(cur, self.run_id, row)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning("Песочница: запись сделки в БД не удалась: %s", e)
        if action == "open":
            logger.info(
                "Песочница open %s @ %s | conf=%.2f | %s | lev=%.2f | notional=$%.2f",
                side, price, signal_confidence, entry_type or "microstructure", leverage, notional_usd,
            )
        else:
            pnl_str = f"realized=${realized_pnl_usd:.2f}" if realized_pnl_usd is not None else "—"
            logger.info(
                "Песочница close %s @ %s | %s | %s | %s",
                side, price, pnl_str, exit_reason or "microstructure", (reason or "")[:60],
            )

    def _log_skip(self, ts_sec: int, direction: str, confidence: float, skip_reason: str) -> None:
        """Пишет в sandbox_skips.csv запись о пропущенном входе (сработал фильтр)."""
        from datetime import datetime
        row = {
            "ts_utc": datetime.utcfromtimestamp(ts_sec).strftime("%Y-%m-%d %H:%M:%S"),
            "ts_unix": ts_sec,
            "direction": direction,
            "confidence": round(confidence, 4),
            "skip_reason": skip_reason,
        }
        _append_skip_row(_get_skips_log_path(), row)
        if self.run_id:
            try:
                from ..core.database import get_connection, insert_sandbox_skip
                conn = get_connection()
                cur = conn.cursor()
                insert_sandbox_skip(cur, self.run_id, row)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning("Песочница: запись пропуска в БД не удалась: %s", e)

    def update(
        self,
        of_result: dict[str, Any],
        current_price: float,
        ts_sec: int,
        *,
        higher_tf_trend: str | None = None,
        context_now: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Обновляет песочницу: сигнал микроструктуры → открытие/закрытие виртуальной позиции.
        При открытии size = initial_balance / current_price. Комиссия списывается при входе и выходе.
        higher_tf_trend: up/down/flat — при trend_filter=True не открывать против тренда.
        context_now: при use_context_now_primary=True вход только при allowed_long/allowed_short (уровень + flow).
        Возвращает состояние после обновления.
        """
        from ..analysis.microstructure_signal import compute_microstructure_signal
        from ..core import config as _config

        min_score = float(getattr(_config, "MICROSTRUCTURE_MIN_SCORE", 0.25))
        signal = compute_microstructure_signal(
            of_result,
            min_score_for_direction=min_score,
            current_price=current_price,
            now_ts_sec=ts_sec,
        )
        self.last_signal = signal
        self.last_ts = ts_sec
        direction = signal.get("direction", "none")
        confidence = float(signal.get("confidence") or 0.0)
        reason = signal.get("reason", "") or ""
        exit_hints = signal.get("exit_hints") or []
        # Режим «только context_now»: направление и уверенность только из контекста «здесь и сейчас» (без микроструктуры)
        if self.use_context_now_only and context_now:
            if context_now.get("allowed_long"):
                direction = "long"
                confidence = min(1.0, max(0.5, abs(float(context_now.get("short_window_delta_ratio") or 0)) * 2))
                reason = "context_now only: at_support + flow_bullish"
            elif context_now.get("allowed_short"):
                direction = "short"
                confidence = min(1.0, max(0.5, abs(float(context_now.get("short_window_delta_ratio") or 0)) * 2))
                reason = "context_now only: at_resistance + flow_bearish"
            else:
                direction = "none"
                confidence = 0.0
                reason = "context_now only: no level+flow"

        equity = self.equity(current_price)
        self._peak_equity = max(self._peak_equity, equity)
        self._closed_this_tick = False

        # Кулдаун: после выхода не открываем новую позицию N секунд
        in_cooldown = (
            self.cooldown_sec > 0
            and self.last_close_ts > 0
            and (ts_sec - self.last_close_ts) < self.cooldown_sec
        )

        # Задержка входа после sweep: не открывать в течение N секунд после последнего sweep (защита от ловушек)
        in_sweep_delay = False
        if self.sweep_delay_sec > 0:
            sweeps = of_result.get("sweeps") or {}
            last_sweep_time_raw = sweeps.get("last_sweep_time")
            if last_sweep_time_raw is not None:
                try:
                    sweep_ts_sec = float(last_sweep_time_raw) / 1000.0 if float(last_sweep_time_raw) > 1e12 else float(last_sweep_time_raw)
                    in_sweep_delay = (ts_sec - sweep_ts_sec) < self.sweep_delay_sec
                except (TypeError, ValueError):
                    pass

        # Тики «в нашу сторону»: направление совпадает с позицией (для мин. удержания по микроструктуре)
        if self.position != 0:
            dir_ok = (self.position == 1 and direction == "long") or (self.position == -1 and direction == "short")
            if dir_ok:
                self._confirming_ticks += 1
            # else не сбрасываем счётчик — считаем накопленные с входа

        # Сигнал на выход: none/против ИЛИ уверенность ниже порога (трейлинг по микроструктуре, п.1–2)
        want_exit_dir = direction == "none" or (direction == "long" and self.position == -1) or (direction == "short" and self.position == 1)
        want_exit_conf = self.exit_min_confidence > 0 and confidence < self.exit_min_confidence
        want_exit = want_exit_dir or want_exit_conf

        if self.position != 0:
            if want_exit:
                self._exit_signal_ticks += 1
            else:
                self._exit_signal_ticks = 0
            # Окно подтверждения выхода (п.5): последние M тиков, нужно N с флагом «на выход»
            if self.exit_window_ticks > 0 and self.exit_window_need > 0:
                self._exit_window.append(want_exit)
                if len(self._exit_window) > self.exit_window_ticks:
                    self._exit_window.pop(0)
                exit_window_ok = len(self._exit_window) >= self.exit_window_ticks and sum(self._exit_window) >= self.exit_window_need
            else:
                exit_window_ok = True  # не используем окно — решаем по подряд тикам

        # Выход по цене (п.4): стоп-лосс / безубыток / тейк-профит (один уровень или частичный TP)
        exit_by_price = False
        exit_price_reason = ""
        pct_chg = 0.0
        if self.position != 0 and self.entry_price > 0:
            if self.position == 1:  # long
                pct_chg = (current_price - self.entry_price) / self.entry_price
            else:  # short
                pct_chg = (self.entry_price - current_price) / self.entry_price
            pct_chg *= 100.0
            # Перенос стопа в безубыток: при прибыли >= порога один раз переключаем флаг
            if (
                self.breakeven_trigger_pct > 0
                and self.stop_loss_pct > 0
                and not self._sl_at_breakeven
                and pct_chg >= self.breakeven_trigger_pct
            ):
                self._sl_at_breakeven = True
            # Стоп-лосс: либо обычный уровень, либо безубыток (выход при pct_chg <= 0)
            if self.stop_loss_pct > 0:
                if self._sl_at_breakeven:
                    if pct_chg <= 0:
                        exit_by_price = True
                        exit_price_reason = f"breakeven {pct_chg:.2f}%"
                elif pct_chg <= -self.stop_loss_pct:
                    exit_by_price = True
                    exit_price_reason = f"stop_loss {pct_chg:.2f}%"
            if not exit_by_price and not self.take_profit_levels and self.take_profit_pct > 0 and pct_chg >= self.take_profit_pct:
                exit_by_price = True
                exit_price_reason = f"take_profit {pct_chg:.2f}%"
            # Трейлинг: при прибыли >= trail_trigger_pct отслеживаем пик; закрыть при откате на trail_pct от пика
            if (
                not exit_by_price
                and self.trail_trigger_pct > 0
                and self.trail_pct > 0
                and pct_chg >= self.trail_trigger_pct
            ):
                self._trail_peak_pct = max(self._trail_peak_pct, pct_chg)
                if self._trail_peak_pct > 0 and pct_chg <= self._trail_peak_pct - self.trail_pct:
                    exit_by_price = True
                    exit_price_reason = f"trailing_stop {pct_chg:.2f}% (peak {self._trail_peak_pct:.2f}%)"

        def _do_close(close_reason: str) -> None:
            realized_gross = self.unrealized_pnl(current_price)
            notional = self.size * current_price
            commission_close = notional * self.taker_fee
            self.total_commission += commission_close
            self.total_realized_pnl += realized_gross
            side = "long" if self.position == 1 else "short"
            lev = self._current_leverage
            self._margin_used = 0.0
            self._current_leverage = 1.0
            exit_reason = _classify_exit_reason(close_reason)
            self._log_trade(
                ts_sec, "close", side, current_price, self.size, notional,
                commission_close, realized_gross, direction, confidence, close_reason,
                leverage=lev,
                exit_reason=exit_reason,
            )
            self.last_close_ts = ts_sec
            self._exit_signal_ticks = 0
            self._exit_window.clear()
            self._closed_this_tick = True
            self.position = 0
            self.entry_price = 0.0
            self.size = 0.0
            self.entry_ts = 0
            self._initial_size = 0.0
            self._tp_closed_share = 0.0
            self._sl_at_breakeven = False
            self._trail_peak_pct = 0.0

        def _do_partial_close(close_share: float, current_pct: float) -> None:
            """Закрыть долю позиции по частичному TP. close_share — доля от начального размера (0..1)."""
            if self._initial_size <= 0 or close_share <= 0 or self.size <= 0:
                return
            close_size = min(self._initial_size * close_share, self.size)
            if close_size <= 0:
                return
            if self.position == 1:  # long
                realized_gross = close_size * (current_price - self.entry_price)
            else:  # short
                realized_gross = close_size * (self.entry_price - current_price)
            notional = close_size * current_price
            commission_close = notional * self.taker_fee
            self.total_commission += commission_close
            self.total_realized_pnl += realized_gross
            self.size -= close_size
            self._tp_closed_share += close_size / self._initial_size
            side = "long" if self.position == 1 else "short"
            reason = f"take_profit_part {current_pct:.2f}% ({int(close_share * 100)}%)"
            self._log_trade(
                ts_sec, "close", side, current_price, close_size, notional,
                commission_close, realized_gross, direction, confidence, reason,
                leverage=self._current_leverage,
                exit_reason="take_profit_part",
            )
            if self.size <= 0 or self._tp_closed_share >= 0.9999:
                self.position = 0
                self.entry_price = 0.0
                self.size = 0.0
                self.entry_ts = 0
                self._initial_size = 0.0
                self._tp_closed_share = 0.0
                self._sl_at_breakeven = False
                self._trail_peak_pct = 0.0
                self._margin_used = 0.0
                self._current_leverage = 1.0
                self.last_close_ts = ts_sec
                self._exit_signal_ticks = 0
                self._exit_window.clear()
                self._closed_this_tick = True

        # Ликвидация при плече: убыток >= маржа * liquidation_maintenance
        if self.position != 0 and self._margin_used > 0 and self.liquidation_maintenance > 0:
            if self.unrealized_pnl(current_price) <= -self._margin_used * self.liquidation_maintenance:
                _do_close("liquidation")
        # Закрытие по цене (стоп/тейк) — без ожидания min_hold / тиков
        if self.position != 0 and exit_by_price:
            _do_close(exit_price_reason)
        # Частичный тейк-профит по уровням (если заданы SANDBOX_TP_LEVELS)
        elif self.position != 0 and self.take_profit_levels and pct_chg > 0 and self._initial_size > 0:
            for level_pct, cumulative_share in self.take_profit_levels:
                if pct_chg >= level_pct and self._tp_closed_share < cumulative_share:
                    share_to_close = cumulative_share - self._tp_closed_share
                    _do_partial_close(share_to_close, pct_chg)
                    if self.position == 0:
                        break
        # Закрытие по микроструктуре: min_hold_sec, мин. тиков «в нашу сторону», N подряд или окно
        elif self.position != 0 and want_exit:
            held_sec = ts_sec - self.entry_ts
            confirming_ok = self.min_confirming_ticks <= 0 or self._confirming_ticks >= self.min_confirming_ticks
            consecutive_ok = self.exit_window_ticks <= 0 and self._exit_signal_ticks >= self.exit_none_ticks
            if self.exit_window_ticks > 0 and self.exit_window_need > 0:
                consecutive_ok = exit_window_ok
            # Не закрывать по микроструктуре в плюсе, пока профит меньше min_profit_pct (чтобы отбить комиссию)
            allow_microstructure_close = True
            if self.min_profit_pct > 0 and self.entry_price > 0:
                unrealized = self.unrealized_pnl(current_price)
                if unrealized > 0:
                    if self.position == 1:
                        pct_chg = (current_price - self.entry_price) / self.entry_price * 100.0
                    else:
                        pct_chg = (self.entry_price - current_price) / self.entry_price * 100.0
                    if pct_chg < self.min_profit_pct:
                        allow_microstructure_close = False
            if held_sec >= self.min_hold_sec and confirming_ok and consecutive_ok and allow_microstructure_close:
                _do_close(reason)

        # Открытие при long/short (кулдаун, порог уверенности, фильтр тренда, не в тот же тик что close)
        # Дивергенция дельта/цена: не входить против (bearish → блок long, bullish → блок short)
        div = of_result.get("delta_price_divergence") or {}
        divergence_block_long = bool(div.get("bearish_divergence"))
        divergence_block_short = bool(div.get("bullish_divergence"))
        # Горячие уровни T&S: не входить long прямо под сопротивлением по объёму, short — над поддержкой
        hot_block_long = _price_near_hot_resistance(current_price, of_result, distance_pct=0.002)
        hot_block_short = _price_near_hot_support(current_price, of_result, distance_pct=0.002)

        def _would_open_long() -> bool:
            return (
                direction == "long"
                and confidence >= self.min_confidence_to_open
                and (not self.use_context_now_primary or not context_now or context_now.get("allowed_long"))
                and not divergence_block_long
                and not hot_block_long
            )

        def _would_open_short() -> bool:
            return (
                direction == "short"
                and confidence >= self.min_confidence_to_open
                and (not self.use_context_now_primary or not context_now or context_now.get("allowed_short"))
                and not divergence_block_short
                and not hot_block_short
            )

        if in_cooldown:
            if _would_open_long():
                self._log_skip(ts_sec, "long", confidence, "cooldown")
            if _would_open_short():
                self._log_skip(ts_sec, "short", confidence, "cooldown")
            pass
        elif self.no_open_same_tick_as_close and self._closed_this_tick:
            if _would_open_long():
                self._log_skip(ts_sec, "long", confidence, "same_tick_as_close")
            if _would_open_short():
                self._log_skip(ts_sec, "short", confidence, "same_tick_as_close")
            pass  # не открывать в тот же тик после закрытия — избежать мгновенного разворота
        elif self.no_open_sweep_only and signal.get("sweep_only"):
            if _would_open_long():
                self._log_skip(ts_sec, "long", confidence, "sweep_only")
            if _would_open_short():
                self._log_skip(ts_sec, "short", confidence, "sweep_only")
            pass  # не открывать по одному sweep без подтверждения delta/imbalance (защита от ловушек)
        elif in_sweep_delay:
            if _would_open_long():
                self._log_skip(ts_sec, "long", confidence, "sweep_delay")
            if _would_open_short():
                self._log_skip(ts_sec, "short", confidence, "sweep_delay")
            pass  # не открывать сразу после sweep — дать время проявиться движению
        elif _would_open_long():
            if self.trend_filter and higher_tf_trend == "down":
                self._log_skip(ts_sec, "long", confidence, "trend_filter")
                pass  # не открываем long против тренда вниз
            elif self.position != 1:
                if self.position == -1:
                    realized_gross = self.unrealized_pnl(current_price)
                    notional = self.size * current_price
                    commission_close = notional * self.taker_fee
                    self.total_commission += commission_close
                    self.total_realized_pnl += realized_gross
                    lev_prev = self._current_leverage
                    self._margin_used = 0.0
                    self._current_leverage = 1.0
                    self._log_trade(
                        ts_sec, "close", "short", current_price, self.size, notional,
                        commission_close, realized_gross, direction, confidence, reason,
                        leverage=lev_prev,
                        exit_reason="microstructure",
                    )
                    self.last_close_ts = ts_sec
                    self._closed_this_tick = True
                    self.position = 0
                    self.entry_price = 0.0
                    self.size = 0.0
                    self.entry_ts = 0
                    self._initial_size = 0.0
                    self._tp_closed_share = 0.0
                    self._sl_at_breakeven = False
                    self._trail_peak_pct = 0.0
                if not self._closed_this_tick:
                    leverage = self._compute_leverage(confidence, equity)
                    margin = max(self.initial_balance * 0.01, equity * self.margin_fraction)
                    notional_open = margin * leverage
                    self.position = 1
                    self.entry_price = current_price
                    self.size = notional_open / current_price if current_price > 0 else 0.0
                    self.entry_ts = ts_sec
                    self._margin_used = notional_open / leverage if leverage > 0 else 0.0
                    self._current_leverage = leverage
                    self._exit_signal_ticks = 0
                    self._confirming_ticks = 0
                    self._exit_window.clear()
                    self._initial_size = self.size
                    self._tp_closed_share = 0.0
                    commission_open = notional_open * self.taker_fee
                    self.total_commission += commission_open
                    entry_type = "context_now_only" if self.use_context_now_only else ("context_now_primary" if context_now else "microstructure")
                    self._log_trade(
                        ts_sec, "open", "long", self.entry_price, self.size, notional_open,
                        commission_open, None, direction, confidence, reason,
                        leverage=leverage,
                        entry_type=entry_type,
                    )
        elif _would_open_short():
            if self.trend_filter and higher_tf_trend == "up":
                self._log_skip(ts_sec, "short", confidence, "trend_filter")
                pass  # не открываем short против тренда вверх
            elif self.position != -1:
                if self.position == 1:
                    realized_gross = self.unrealized_pnl(current_price)
                    notional = self.size * current_price
                    commission_close = notional * self.taker_fee
                    self.total_commission += commission_close
                    self.total_realized_pnl += realized_gross
                    lev_prev = self._current_leverage
                    self._margin_used = 0.0
                    self._current_leverage = 1.0
                    self._log_trade(
                        ts_sec, "close", "long", current_price, self.size, notional,
                        commission_close, realized_gross, direction, confidence, reason,
                        leverage=lev_prev,
                        exit_reason="microstructure",
                    )
                    self.last_close_ts = ts_sec
                    self._closed_this_tick = True
                    self.position = 0
                    self.entry_price = 0.0
                    self.size = 0.0
                    self.entry_ts = 0
                    self._initial_size = 0.0
                    self._tp_closed_share = 0.0
                    self._sl_at_breakeven = False
                    self._trail_peak_pct = 0.0
                if not self._closed_this_tick:
                    leverage = self._compute_leverage(confidence, equity)
                    margin = max(self.initial_balance * 0.01, equity * self.margin_fraction)
                    notional_open = margin * leverage
                    self.position = -1
                    self.entry_price = current_price
                    self.size = notional_open / current_price if current_price > 0 else 0.0
                    self.entry_ts = ts_sec
                    self._margin_used = notional_open / leverage if leverage > 0 else 0.0
                    self._current_leverage = leverage
                    self._exit_signal_ticks = 0
                    self._confirming_ticks = 0
                    self._exit_window.clear()
                    self._initial_size = self.size
                    self._tp_closed_share = 0.0
                    commission_open = notional_open * self.taker_fee
                    self.total_commission += commission_open
                    entry_type = "context_now_only" if self.use_context_now_only else ("context_now_primary" if context_now else "microstructure")
                    self._log_trade(
                        ts_sec, "open", "short", self.entry_price, self.size, notional_open,
                        commission_open, None, direction, confidence, reason,
                        leverage=leverage,
                        entry_type=entry_type,
                    )

        state = self.get_state()
        state["unrealized_pnl"] = round(self.unrealized_pnl(current_price), 4)
        state["current_price"] = current_price
        state["equity_usd"] = round(self.equity(current_price), 4)
        state["last_signal_reason"] = signal.get("reason", "")
        return state

    def get_summary(self, current_price: float) -> dict[str, Any]:
        """
        Сводка для анализа: кол-во сделок, входов/выходов, комиссии, выигрышные/убыточные, выходы по причинам.
        """
        closes = [t for t in self.trades if t.get("action") == "close"]
        pnls = [float(t.get("realized_pnl_usd") or 0) for t in closes]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        exits_by: dict[str, int] = {}
        for t in closes:
            r = (t.get("exit_reason") or "").strip() or "microstructure"
            exits_by[r] = exits_by.get(r, 0) + 1
        return {
            "trades_count": len(self.trades),
            "opens_count": sum(1 for t in self.trades if t.get("action") == "open"),
            "closes_count": len(closes),
            "total_commission_usd": round(self.total_commission, 4),
            "total_realized_pnl_gross": round(self.total_realized_pnl, 4),
            "total_realized_pnl_net": round(self.total_realized_pnl - self.total_commission, 4),
            "winning_trades": wins,
            "losing_trades": losses,
            "equity_usd": round(self.equity(current_price), 4),
            "exits_by": exits_by,
        }
