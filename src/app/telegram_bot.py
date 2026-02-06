"""
Управление ботом через Telegram.
Команды: /start, /help, /signal, /status, /sandbox, /sandbox_logs, /zones, /zones_chart, /zones_1h, /momentum, /db, /health, /backtest_phases, /chart, /phases, /trend_daily, /trend_backtest, /trade_2025, /id.
Reply-панель + inline-кнопки: Сигнал | Зоны | Импульс | Песочница | Обновить | БД. Алерт при смене сигнала (TELEGRAM_ALERT_*).
Запуск: python telegram_bot.py (launcher в корне).
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from io import BytesIO
from pathlib import Path

from ..core import config
from ..core.database import get_connection, get_db_path, get_candles, count_candles
from ..core import db_helper
from ..analysis.multi_tf import analyze_multi_timeframe
from ..scripts.backtest_phases import run_for_chart
from ..scripts import backtest_trend
from .db_sync import close, open_and_prepare, refresh_if_due

try:
    from telegram import (
        BotCommand,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        KeyboardButton,
        ReplyKeyboardMarkup,
        ReplyKeyboardRemove,
    )
    from telegram.error import BadRequest
except ImportError:
    BotCommand = InlineKeyboardButton = InlineKeyboardMarkup = None  # type: ignore
    KeyboardButton = ReplyKeyboardMarkup = ReplyKeyboardRemove = None  # type: ignore
    BadRequest = None  # type: ignore

logger = logging.getLogger(__name__)

# Эмодзи по направлению сигнала
DIR_EMOJI = {"long": "🟢 Long", "short": "🔴 Short", "none": "⚪ None"}

HELP_TEXT = """<b>Сигнал и фазы</b>
/signal — полный разбор: сигнал, фазы по ТФ, зоны, импульс
/status — одна строка: сигнал и старший ТФ

<b>Зоны и импульс</b>
/zones — торговые зоны: поддержка/сопротивление, перевороты, confluence (текст)
/zones_chart — график торговых зон по всей БД ТФ D (свечи + уровни S/R)
/zones_1h — торговые зоны на ТФ 1 ч за последние 2 нед.
/momentum — импульс: состояние (сильный/затухающий), RSI, направление

<b>Графики</b>
/chart — свечной график с трендами Вверх/Вниз/Флэт
/phases — график 6 фаз рынка (Накопление, Рост, Распределение…)
/trend_daily — тренд по всей БД ТФ D (свечи + зоны Вверх/Вниз/Флэт)
/trend_backtest — бэктест тренда по всей БД: точность по направлениям (график)
/trade_2025 [год] — бэктест сценария управления сделкой по всем ТФ за год: график PnL и итог (старт $100)
/backtest_phases — график бэктеста фаз

<b>БД и мониторинг</b>
/db — статистика базы свечей
/health — свежесть БД по ТФ, последнее обновление
/sandbox — песочница микроструктуры: позиция, PnL, эквити в реальном времени (при ORDERFLOW + песочница)
/sandbox_logs — выгрузить файлы логов песочницы (сделки, сводки, сессии, пропуски) в чат

<b>Прочее</b>
/id — твой Telegram user id (для TELEGRAM_ALLOWED_IDS)
/help — это сообщение

Под сообщениями — кнопки: Сигнал | Зоны | Импульс | Песочница | Обновить"""

# Кнопки нижней панели (Reply)
BTN_SIGNAL = "📊 Сигнал"
BTN_DB = "🗄 БД"
BTN_ID = "🆔 Мой ID"
BTN_HELP = "❓ Помощь"
BTN_HIDE = "⬇ Скрыть панель"

# Callback data для inline-кнопок
CB_SIGNAL = "cb_signal"
CB_ZONES = "cb_zones"
CB_MOMENTUM = "cb_momentum"
CB_DB = "cb_db"
CB_REFRESH_SIGNAL = "cb_refresh_signal"
CB_REFRESH_ZONES = "cb_refresh_zones"
CB_REFRESH_MOMENTUM = "cb_refresh_momentum"
CB_REFRESH_DB = "cb_refresh_db"
CB_SANDBOX = "cb_sandbox"
CB_REFRESH_SANDBOX = "cb_refresh_sandbox"
CB_SANDBOX_LOGS = "cb_sandbox_logs"

MAIN_KEYBOARD = [
    [BTN_SIGNAL, BTN_DB],
    [BTN_ID, BTN_HELP],
    [BTN_HIDE],
]

MAX_MESSAGE_LENGTH = 4096

# Таймфреймы понятным языком (код Bybit → подпись для пользователя)
TF_LABELS: dict[str, str] = {
    "1": "1 мин",
    "3": "3 мин",
    "5": "5 мин",
    "15": "15 мин",
    "30": "30 мин",
    "60": "1 ч",
    "120": "2 ч",
    "240": "4 ч",
    "360": "6 ч",
    "720": "12 ч",
    "D": "День",
    "W": "Неделя",
    "M": "Месяц",
}


def _tf_label(tf: str) -> str:
    """Возвращает читаемое название таймфрейма; для неизвестного — как есть."""
    if not tf:
        return "—"
    key = str(tf).strip().upper()
    return TF_LABELS.get(key, tf)


def _tf_sort_key(tf: str) -> tuple[int, str]:
    """Ключ для сортировки таймфреймов: 1м → 3м → … → 1ч → … → День → Неделя → Месяц."""
    s = str(tf).strip().upper()
    if s == "D":
        return (1_000_000, "D")
    if s == "W":
        return (2_000_000, "W")
    if s == "M":
        return (3_000_000, "M")
    try:
        return (int(s), s)
    except ValueError:
        return (0, s)


def _check_allowed(user_id: int) -> bool:
    """Разрешён ли пользователь (если TELEGRAM_ALLOWED_IDS пуст — разрешены все)."""
    if not config.TELEGRAM_ALLOWED_IDS:
        return True
    return user_id in config.TELEGRAM_ALLOWED_IDS


def _split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Разбивает длинный текст на части по max_len, по границам абзацев/строк."""
    if len(text) <= max_len:
        return [text] if text else []
    chunks = []
    rest = text
    while rest:
        if len(rest) <= max_len:
            chunks.append(rest)
            break
        block = rest[: max_len + 1]
        for sep in ("\n\n", "\n", " "):
            idx = block.rfind(sep)
            if idx != -1:
                chunks.append(rest[: idx + 1].rstrip())
                rest = rest[idx + 1 :].lstrip()
                break
        else:
            chunks.append(rest[:max_len])
            rest = rest[max_len:]
    return chunks


def _get_signal_text(db_conn=None) -> str:
    """Синхронный запрос анализа и форматирование текста для Telegram (с эмодзи). db_conn — для DATA_SOURCE=db."""
    try:
        r = analyze_multi_timeframe(db_conn=db_conn)
        direction = (r["signals"].get("direction") or "none").lower()
        emoji_dir = DIR_EMOJI.get(direction, direction.upper())
        conf = r["signals"].get("confidence")
        conf_lvl = r["signals"].get("confidence_level", "—")
        phase_ready = r["signals"].get("phase_decision_ready", False)
        tfs = r.get("timeframes") or {}
        higher_tf_key = list(tfs)[-1] if tfs else None
        higher_label = _tf_label(higher_tf_key or "")
        entry_score = r["signals"].get("entry_score")
        lines = [
            f"Сигнал: {emoji_dir}",
            f"Уверенность: {conf} ({conf_lvl})" if conf is not None else "",
            f"Единый score входа: {entry_score}" if entry_score is not None else "",
            f"Готов к решению: {'да' if phase_ready else 'нет'}",
            f"Причина: {r['signals'].get('reason', '—')}",
        ]
        if r.get("market_state_narrative"):
            lines.append(f"Сейчас (prop): {r['market_state_narrative']}")
        lines.append("")
        lines.append(f"Старший ТФ ({higher_label}): тренд {r.get('higher_tf_trend', '?')} ({r.get('higher_tf_trend_ru', '—')}), фаза {r.get('higher_tf_phase_ru', '—')}")
        regime_ru = r.get("higher_tf_regime_ru") or "—"
        regime_ok = r.get("regime_ok", True)
        candle_ok = r.get("candle_quality_ok", True)
        lines.append(f"  Режим: {regime_ru}, ок={regime_ok} | Качество свечей: {'ок' if candle_ok else 'низкое'}")
        trend_str = r.get("higher_tf_trend_strength")
        trend_conf = r.get("higher_tf_trend_confidence")
        trend_unclear = r.get("higher_tf_trend_unclear", True)
        if trend_str is not None or trend_conf is not None:
            parts = []
            if trend_str is not None:
                parts.append(f"сила={trend_str:.2f}")
            if trend_conf is not None:
                parts.append(f"уверенность={trend_conf * 100:.0f}%")
            parts.append("неясен" if trend_unclear else "ясен")
            lines.append(f"  Тренд: {', '.join(parts)}")
        phase_unclear = r.get("higher_tf_phase_unclear", True)
        phase_stable = r.get("higher_tf_phase_stable", False)
        score_gap = r.get("higher_tf_score_gap")
        sec_phase = r.get("higher_tf_secondary_phase_ru") or "—"
        phase_parts = [f"вторая={sec_phase}"]
        if score_gap is not None:
            phase_parts.append(f"разрыв={score_gap:.2f}")
        phase_parts.append(f"неясна={phase_unclear}, устойчива={phase_stable}")
        lines.append("  Фаза: " + ", ".join(phase_parts))
        # Зоны (поддержка/сопротивление, перевороты, confluence)
        zones = r.get("trading_zones") or {}
        if zones.get("levels") is not None:
            lines.append("")
            lines.append("Зоны (старший ТФ):")
            z_low = zones.get("zone_low")
            z_high = zones.get("zone_high")
            in_z = zones.get("in_zone", False)
            at_sup = zones.get("at_support_zone", False)
            at_res = zones.get("at_resistance_zone", False)
            n_conf = zones.get("levels_with_confluence", 0)
            lines.append(f"  Зона: {z_low:.2f}–{z_high:.2f}" if z_low is not None and z_high is not None else "  Зона: —")
            lines.append(f"  В зоне: {'да' if in_z else 'нет'} | у поддержки: {'да' if at_sup else 'нет'} | у сопротивления: {'да' if at_res else 'нет'} | confluence уровней: {n_conf}")
            ns = zones.get("nearest_support")
            nr = zones.get("nearest_resistance")
            if ns:
                dist_s = r.get("distance_to_support_pct")
                s_str = f"  Поддержка: {ns.get('price', 0):.2f}" + (f" ({dist_s:.2%})" if dist_s is not None else "")
                lines.append(s_str)
            if nr:
                dist_r = r.get("distance_to_resistance_pct")
                r_str = f"  Сопротивление: {nr.get('price', 0):.2f}" + (f" ({dist_r:.2%})" if dist_r is not None else "")
                lines.append(r_str)
            flips = zones.get("recent_flips") or []
            if flips:
                lines.append(f"  Перевороты: {len(flips)}")
                for flip in flips[:3]:
                    lines.append(f"    {flip.get('price', 0):.2f} {flip.get('origin_role', '?')} → {flip.get('current_role', '?')}")
        # Импульс по старшему ТФ
        mom_state = r.get("higher_tf_momentum_state_ru") or "—"
        mom_dir = r.get("higher_tf_momentum_direction_ru") or "—"
        mom_rsi = r.get("higher_tf_momentum_rsi")
        mom_ret = r.get("higher_tf_momentum_return_5")
        lines.append("")
        lines.append("Импульс (старший ТФ):")
        lines.append(f"  Состояние: {mom_state}, направление: {mom_dir}" + (f", RSI: {mom_rsi:.0f}" if mom_rsi is not None else "") + (f", return_5: {mom_ret:.2%}" if mom_ret is not None else ""))
        # Разбор score входа
        br = r["signals"].get("entry_score_breakdown") or {}
        if br:
            parts = [f"phase={br.get('phase', 0):.2f}", f"trend={br.get('trend', 0):.2f}", f"tf_align={br.get('tf_align_ratio', 0):.2f}"]
            if br.get("stability_bonus"):
                parts.append(f"bonus={br.get('stability_bonus'):.2f}")
            lines.append("  Score: " + ", ".join(parts))
        lines.extend(["", "По таймфреймам:"])
        lines = [x for x in lines if x]
        for tf, d in tfs.items():
            trend = d.get("trend", "?")
            trend_s = d.get("trend_strength")
            trend_c = d.get("trend_confidence")
            phase = d.get("phase_ru", "—")
            score = d.get("phase_score")
            score_str = f" ({score:.2f})" if score is not None else ""
            n = len(d.get("candles", []))
            reg = d.get("regime_ru") or "—"
            q_ok = d.get("candle_quality_ok", True)
            trend_extra = ""
            if trend_s is not None and trend_c is not None:
                trend_extra = f", тренд уверенность={trend_c * 100:.0f}%"
            lines.append(f"  {_tf_label(tf)}: тренд={trend}{f' (сила={trend_s:.2f})' if trend_s is not None else ''}, фаза={phase}{score_str}, режим={reg}, качество={'ок' if q_ok else 'низкое'}{trend_extra}, свечей={n}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Ошибка при запросе сигнала: %s", e)
        return f"Ошибка: {e}"


def _get_status_text(db_conn=None) -> str:
    """Одна строка: сигнал + пара + старший таймфрейм + уверенность. db_conn — для DATA_SOURCE=db."""
    try:
        r = analyze_multi_timeframe(db_conn=db_conn)
        direction = (r["signals"].get("direction") or "none").lower()
        emoji_dir = DIR_EMOJI.get(direction, direction.upper())
        conf_lvl = r["signals"].get("confidence_level", "—")
        tfs = r.get("timeframes") or {}
        higher_tf_key = list(tfs)[-1] if tfs else None
        higher_label = _tf_label(higher_tf_key or "")
        trend = r.get("higher_tf_trend", "?")
        phase_ru = r.get("higher_tf_phase_ru", "—")
        regime_ru = r.get("higher_tf_regime_ru") or "—"
        entry_score = r["signals"].get("entry_score")
        entry_str = f"  score={entry_score}" if entry_score is not None else ""
        return f"{emoji_dir}  |  {config.SYMBOL}  |  {higher_label}: {trend}, {phase_ru}, режим {regime_ru}{entry_str}  |  {conf_lvl}"
    except Exception as e:
        logger.exception("Ошибка при запросе status: %s", e)
        return f"Ошибка: {e}"


def _get_db_text() -> str:
    """Синхронная статистика БД для Telegram."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        total = count_candles(cur, symbol=config.SYMBOL)
        cur.execute(
            "SELECT timeframe, COUNT(*) FROM klines WHERE symbol = ? GROUP BY timeframe",
            (config.SYMBOL,),
        )
        rows = cur.fetchall()
        conn.close()
        rows_sorted = sorted(rows, key=lambda r: _tf_sort_key(r[0]))
        lines = [f"БД: {get_db_path()}", f"Пара: {config.SYMBOL}", f"Всего свечей: {total}", ""]
        for tf, cnt in rows_sorted:
            lines.append(f"  {_tf_label(tf)}: {cnt}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Ошибка при запросе БД: %s", e)
        return f"Ошибка БД: {e}"


def _get_zones_text(db_conn=None) -> str:
    """Только торговые зоны: поддержка/сопротивление, текущая зона, перевороты, confluence."""
    try:
        r = analyze_multi_timeframe(db_conn=db_conn)
        zones = r.get("trading_zones") or {}
        lines = [
            f"Зоны | {config.SYMBOL}",
            "",
        ]
        if not zones.get("levels"):
            lines.append("Уровней нет (недостаточно данных по старшему ТФ).")
            return "\n".join(lines)
        z_low = zones.get("zone_low")
        z_high = zones.get("zone_high")
        in_z = zones.get("in_zone", False)
        at_sup = zones.get("at_support_zone", False)
        at_res = zones.get("at_resistance_zone", False)
        n_conf = zones.get("levels_with_confluence", 0)
        lines.append(f"Зона: {z_low:.2f} – {z_high:.2f}" if z_low is not None and z_high is not None else "Зона: —")
        lines.append(f"В зоне: {'да' if in_z else 'нет'} | у поддержки: {'да' if at_sup else 'нет'} | у сопротивления: {'да' if at_res else 'нет'}")
        lines.append(f"Уровней с confluence ≥2 ТФ: {n_conf}")
        lines.append("")
        ns = zones.get("nearest_support")
        nr = zones.get("nearest_resistance")
        dist_s = r.get("distance_to_support_pct")
        dist_r = r.get("distance_to_resistance_pct")
        if ns:
            role = (ns.get("origin_role") or "—") + (" → " + (ns.get("current_role") or "") if ns.get("broken") else "")
            lines.append(f"Поддержка: {ns.get('price', 0):.2f} ({role})" + (f" | до уровня {dist_s:.2%}" if dist_s is not None else ""))
        if nr:
            role = (nr.get("origin_role") or "—") + (" → " + (nr.get("current_role") or "") if nr.get("broken") else "")
            lines.append(f"Сопротивление: {nr.get('price', 0):.2f} ({role})" + (f" | до уровня {dist_r:.2%}" if dist_r is not None else ""))
        flips = zones.get("recent_flips") or []
        if flips:
            lines.append("")
            lines.append(f"Перевороты ролей ({len(flips)}):")
            for flip in flips[:5]:
                lines.append(f"  {flip.get('price', 0):.2f}  {flip.get('origin_role', '?')} → {flip.get('current_role', '?')}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Ошибка при запросе зон: %s", e)
        return f"Ошибка: {e}"


def _get_momentum_text(db_conn=None) -> str:
    """Только импульс по старшему ТФ: состояние, направление, RSI, return_5."""
    try:
        r = analyze_multi_timeframe(db_conn=db_conn)
        lines = [
            f"Импульс | {config.SYMBOL}",
            "",
            f"Состояние: {r.get('higher_tf_momentum_state_ru') or '—'} ({r.get('higher_tf_momentum_state', 'neutral')})",
            f"Направление: {r.get('higher_tf_momentum_direction_ru') or '—'}",
        ]
        rsi = r.get("higher_tf_momentum_rsi")
        ret5 = r.get("higher_tf_momentum_return_5")
        if rsi is not None:
            lines.append(f"RSI: {rsi:.0f}")
        if ret5 is not None:
            lines.append(f"Return 5 баров: {ret5:.2%}")
        lines.append("")
        lines.append("Сигнал: " + (r["signals"].get("direction") or "none") + " | уверенность: " + str(r["signals"].get("confidence_level", "—")))
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Ошибка при запросе импульса: %s", e)
        return f"Ошибка: {e}"


def _get_sandbox_text() -> str:
    """Текст состояния песочницы микроструктуры (реальное время). Читает последнее состояние из sandbox_state."""
    try:
        from .sandbox_state import get_last_state
        state = get_last_state()
        if not state:
            return (
                "Песочница микроструктуры\n\n"
                "Нет данных. Включите ORDERFLOW_ENABLED=1 и MICROSTRUCTURE_SANDBOX_ENABLED=1 в .env и перезапустите бота — "
                "тогда основной цикл будет обновлять виртуальную позицию по сигналу микроструктуры, и здесь появится состояние."
            )
        pos = state.get("position_side", "—")
        entry = state.get("entry_price", 0)
        realized = state.get("total_realized_pnl", 0)
        commission = state.get("total_commission", 0)
        unrealized = state.get("unrealized_pnl", 0)
        equity = state.get("equity_usd", 0)
        initial = state.get("initial_balance_usd", 0)
        trades_count = state.get("trades_count", 0)
        signal_dir = state.get("last_signal_direction", "—")
        signal_conf = state.get("last_signal_confidence", 0)
        reason = state.get("last_signal_reason", "")
        price = state.get("current_price")
        lines = [
            f"Песочница микроструктуры | {config.SYMBOL}",
            "",
            f"Позиция: {pos}",
            f"Цена входа: {entry:.2f}" if entry else "—",
            f"Текущая цена: {price:.2f}" if price else "—",
            "",
            f"Старт: ${initial:.0f}",
            f"Реализовано PnL: ${realized:.2f}",
            f"Комиссия: ${commission:.2f}",
            f"Нереализовано PnL: ${unrealized:.2f}",
            f"Эквити: ${equity:.2f}",
            f"Сделок: {trades_count}",
            "",
            f"Последний сигнал: {signal_dir} (уверенность {signal_conf:.2f})",
        ]
        if reason:
            lines.append(f"Причина: {reason}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Ошибка при запросе песочницы: %s", e)
        return f"Ошибка песочницы: {e}"


def _get_sandbox_log_dir() -> Path:
    """Каталог логов песочницы (logs/), тот же что в main и microstructure_sandbox."""
    log_dir = getattr(config, "LOG_DIR", None)
    if log_dir is None:
        log_dir = Path(__file__).resolve().parents[2] / "logs"
    if isinstance(log_dir, str):
        log_dir = Path(log_dir)
    return log_dir


SANDBOX_LOG_FILES = [
    ("sandbox_trades.csv", "Сделки (CSV)"),
    ("sandbox_result.txt", "Сводки сессий (TXT)"),
    ("sandbox_sessions.csv", "Сессии (CSV)"),
    ("sandbox_skips.csv", "Пропуски входов (CSV)"),
]


async def _send_sandbox_logs(chat_id: int, bot, message_for_action=None) -> None:
    """Отправляет файлы логов песочницы в чат (документы). Отправляет только существующие файлы."""
    if message_for_action and hasattr(message_for_action, "reply_chat_action"):
        await message_for_action.reply_chat_action("upload_document")
    log_dir = _get_sandbox_log_dir()
    sent = 0
    for filename, _ in SANDBOX_LOG_FILES:
        path = log_dir / filename
        if not path.is_file():
            continue
        try:
            with open(path, "rb") as f:
                content = f.read()
            await asyncio.wait_for(
                bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(content),
                    filename=filename,
                    caption=filename,
                ),
                timeout=30.0,
            )
            sent += 1
        except asyncio.TimeoutError:
            logger.warning("Таймаут отправки %s в Telegram", filename)
        except Exception as e:
            logger.exception("Ошибка отправки %s: %s", filename, e)
    if sent == 0:
        await bot.send_message(
            chat_id,
            "Нет файлов логов песочницы (sandbox_trades.csv, sandbox_result.txt и др.). "
            "Запустите бота с ORDERFLOW_ENABLED=1 и MICROSTRUCTURE_SANDBOX_ENABLED=1.",
        )
    else:
        await bot.send_message(chat_id, f"Отправлено файлов: {sent}.")


def _get_health_text(db_conn=None) -> str:
    """Свежесть БД по ТФ: последняя свеча, время обновления."""
    try:
        conn = db_conn or get_connection()
        if conn is None:
            return "БД недоступна (TIMEFRAMES_DB пуст)."
        cur = conn.cursor()
        tfs = getattr(config, "TIMEFRAMES_DB", None) or getattr(config, "TIMEFRAMES", ["15", "60", "240"])
        if not tfs:
            return "Нет таймфреймов в конфиге."
        from datetime import datetime
        lines = [f"Health | {config.SYMBOL}", ""]
        for tf in sorted(tfs, key=_tf_sort_key):
            try:
                rows = get_candles(cur, config.SYMBOL, tf, limit=1, order_asc=False)
                if rows:
                    last = rows[0]
                    ts = last.get("start_time") or 0
                    sec = ts / 1000 if ts > 1e10 else ts
                    dt = datetime.utcfromtimestamp(sec).strftime("%Y-%m-%d %H:%M UTC")
                    lines.append(f"  {_tf_label(tf)}: последняя свеча {dt}")
                else:
                    lines.append(f"  {_tf_label(tf)}: нет данных")
            except Exception as e:
                lines.append(f"  {_tf_label(tf)}: ошибка — {e}")
        if conn is not db_conn:
            conn.close()
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Ошибка при запросе health: %s", e)
        return f"Ошибка: {e}"


def _inline_actions_keyboard(kind: str):
    """Inline-кнопки под сообщением: Сигнал | Зоны | Импульс | Обновить, БД."""
    if InlineKeyboardButton is None or InlineKeyboardMarkup is None:
        return None
    row1 = [
        InlineKeyboardButton("📊 Сигнал", callback_data=CB_SIGNAL),
        InlineKeyboardButton("📐 Зоны", callback_data=CB_ZONES),
        InlineKeyboardButton("📈 Импульс", callback_data=CB_MOMENTUM),
        InlineKeyboardButton("🏖 Песочница", callback_data=CB_SANDBOX),
    ]
    if kind == "signal":
        row2 = [
            InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_SIGNAL),
            InlineKeyboardButton("🗄 БД", callback_data=CB_DB),
        ]
        return InlineKeyboardMarkup([row1, row2])
    if kind == "zones":
        row2 = [
            InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_ZONES),
            InlineKeyboardButton("🗄 БД", callback_data=CB_DB),
        ]
        return InlineKeyboardMarkup([row1, row2])
    if kind == "momentum":
        row2 = [
            InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_MOMENTUM),
            InlineKeyboardButton("🗄 БД", callback_data=CB_DB),
        ]
        return InlineKeyboardMarkup([row1, row2])
    if kind == "sandbox":
        row2 = [
            InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_SANDBOX),
            InlineKeyboardButton("📥 Выгрузить логи", callback_data=CB_SANDBOX_LOGS),
            InlineKeyboardButton("🗄 БД", callback_data=CB_DB),
        ]
        return InlineKeyboardMarkup([row1, row2])
    # kind == "db": только Обновить и Сигнал (как раньше)
    row2 = [
        InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_DB),
        InlineKeyboardButton("📊 Сигнал", callback_data=CB_SIGNAL),
    ]
    return InlineKeyboardMarkup([row2])


def _main_keyboard_markup():
    """Нижняя панель (Reply) с кнопками."""
    if ReplyKeyboardMarkup is None or KeyboardButton is None:
        return None
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t) for t in row] for row in MAIN_KEYBOARD],
        resize_keyboard=True,
        is_persistent=True,
    )


async def _send_long_with_inline(bot, chat_id: int, text: str, kind: str):
    """Шлёт текст частями; под последней частью — inline-кнопки."""
    chunks = _split_message(text)
    keyboard = _inline_actions_keyboard(kind)
    for i, part in enumerate(chunks):
        markup = keyboard if (i == len(chunks) - 1) else None
        await bot.send_message(chat_id=chat_id, text=part, reply_markup=markup)


def _resolve_chat_id(chat_or_message) -> int:
    """Возвращает chat_id. Принимает Message или Chat."""
    if hasattr(chat_or_message, "reply_chat_action"):
        return chat_or_message.chat.id
    return chat_or_message.id


async def _reply_signal(chat_or_message, bot, context=None, send_action=True) -> None:
    chat_id = _resolve_chat_id(chat_or_message)
    if send_action and hasattr(chat_or_message, "reply_chat_action"):
        await chat_or_message.reply_chat_action("typing")
    db_conn = context.application.bot_data.get("db_conn") if context else None
    text = await asyncio.to_thread(_get_signal_text, db_conn)
    await _send_long_with_inline(bot, chat_id, text, "signal")


async def _reply_db(chat_or_message, bot, send_action=True) -> None:
    chat_id = _resolve_chat_id(chat_or_message)
    if send_action and hasattr(chat_or_message, "reply_chat_action"):
        await chat_or_message.reply_chat_action("typing")
    text = await asyncio.to_thread(_get_db_text)
    await _send_long_with_inline(bot, chat_id, text, "db")


async def _reply_zones(chat_or_message, bot, context=None, send_action=True) -> None:
    chat_id = _resolve_chat_id(chat_or_message)
    if send_action and hasattr(chat_or_message, "reply_chat_action"):
        await chat_or_message.reply_chat_action("typing")
    db_conn = context.application.bot_data.get("db_conn") if context else None
    text = await asyncio.to_thread(_get_zones_text, db_conn)
    await _send_long_with_inline(bot, chat_id, text, "zones")


async def _reply_momentum(chat_or_message, bot, context=None, send_action=True) -> None:
    chat_id = _resolve_chat_id(chat_or_message)
    if send_action and hasattr(chat_or_message, "reply_chat_action"):
        await chat_or_message.reply_chat_action("typing")
    db_conn = context.application.bot_data.get("db_conn") if context else None
    text = await asyncio.to_thread(_get_momentum_text, db_conn)
    await _send_long_with_inline(bot, chat_id, text, "momentum")


async def _reply_sandbox(chat_or_message, bot, context=None, send_action=True) -> None:
    chat_id = _resolve_chat_id(chat_or_message)
    if send_action and hasattr(chat_or_message, "reply_chat_action"):
        await chat_or_message.reply_chat_action("typing")
    try:
        text = await asyncio.wait_for(asyncio.to_thread(_get_sandbox_text), timeout=10.0)
    except asyncio.TimeoutError:
        text = (
            "Таймаут 10 с. Запустите бота через main.py с ORDERFLOW_ENABLED=1 и MICROSTRUCTURE_SANDBOX_ENABLED=1."
        )
    except Exception as e:
        logger.exception("Ошибка _reply_sandbox: %s", e)
        text = f"Ошибка песочницы: {e}"
    await _send_long_with_inline(bot, chat_id, text, "sandbox")


async def _reply_health(chat_or_message, bot, context=None) -> None:
    chat_id = _resolve_chat_id(chat_or_message)
    if hasattr(chat_or_message, "reply_chat_action"):
        await chat_or_message.reply_chat_action("typing")
    db_conn = context.application.bot_data.get("db_conn") if context else None
    text = await asyncio.to_thread(_get_health_text, db_conn)
    await bot.send_message(chat_id=chat_id, text=text)


def _get_user_id(update) -> int:
    u = update.effective_user if hasattr(update, "effective_user") else None
    if update.callback_query:
        u = update.callback_query.from_user
    return (u.id if u else 0) or 0


async def cmd_start(update, context) -> None:
    user_id = _get_user_id(update)
    if not _check_allowed(user_id):
        await update.message.reply_text("Доступ запрещён.")
        return
    text = "Бот управления Bybit мультиТФ.\n\n" + HELP_TEXT + "\n\nНижняя панель и кнопки под ответами — быстрый доступ."
    markup = _main_keyboard_markup()
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def cmd_help(update, context) -> None:
    user_id = _get_user_id(update)
    if not _check_allowed(user_id):
        await update.message.reply_text("Доступ запрещён.")
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_signal(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    await _reply_signal(update.message, context.bot, context=context)


async def cmd_status(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    msg = await update.message.reply_text("Считаю…")
    db_conn = context.application.bot_data.get("db_conn") if context else None
    text = await asyncio.to_thread(_get_status_text, db_conn)
    try:
        await msg.edit_text(text)
    except Exception:
        await update.message.reply_text(text)


async def cmd_sandbox(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    chat_id = _resolve_chat_id(update.message)
    bot = context.bot
    msg = None
    # Всегда хотя бы одно сообщение в чат — сначала «Песочница…»
    try:
        msg = await asyncio.wait_for(
            update.message.reply_text("Песочница…"),
            timeout=20.0,
        )
    except asyncio.TimeoutError:
        logger.warning("/sandbox: таймаут при отправке «Песочница…»")
    except Exception as e:
        logger.exception("Ошибка /sandbox при reply: %s", e)
    if msg is None:
        try:
            await asyncio.wait_for(
                bot.send_message(chat_id, "Песочница…"),
                timeout=15.0,
            )
        except Exception:
            pass
    # Получить текст состояния песочницы
    try:
        text = await asyncio.wait_for(
            asyncio.to_thread(_get_sandbox_text),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        text = (
            "Таймаут 10 с. Запустите бота через main.py (не только telegram_bot.py) "
            "и включите в .env ORDERFLOW_ENABLED=1 и MICROSTRUCTURE_SANDBOX_ENABLED=1."
        )
    except Exception as e:
        logger.exception("Ошибка /sandbox: %s", e)
        text = f"Ошибка песочницы: {e}"
    # Отправить результат: по возможности редактируем msg, иначе — новое сообщение
    chunks = _split_message(text)
    keyboard = _inline_actions_keyboard("sandbox")
    if msg is not None:
        try:
            await asyncio.wait_for(
                msg.edit_text(chunks[0], reply_markup=keyboard if len(chunks) == 1 else None),
                timeout=15.0,
            )
        except Exception:
            try:
                await msg.edit_text(chunks[0])
            except Exception:
                await bot.send_message(chat_id, chunks[0], reply_markup=keyboard if len(chunks) == 1 else None)
        for i in range(1, len(chunks)):
            try:
                await asyncio.wait_for(
                    bot.send_message(
                        chat_id,
                        chunks[i],
                        reply_markup=keyboard if i == len(chunks) - 1 else None,
                    ),
                    timeout=15.0,
                )
            except Exception:
                pass
    else:
        for i, chunk in enumerate(chunks):
            try:
                await asyncio.wait_for(
                    bot.send_message(
                        chat_id,
                        chunk,
                        reply_markup=keyboard if i == len(chunks) - 1 else None,
                    ),
                    timeout=15.0,
                )
            except Exception:
                pass


async def cmd_sandbox_logs(update, context) -> None:
    """Команда /sandbox_logs: отправить в чат файлы логов песочницы (trades, result, sessions, skips)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    chat_id = _resolve_chat_id(update.message)
    await _send_sandbox_logs(chat_id, context.bot, message_for_action=update.message)


async def cmd_db(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    await _reply_db(update.message, context.bot)


async def cmd_zones(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    await _reply_zones(update.message, context.bot, context=context)


async def cmd_momentum(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    await _reply_momentum(update.message, context.bot, context=context)


async def cmd_health(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    await _reply_health(update.message, context.bot, context=context)


async def cmd_id(update, context) -> None:
    user_id = _get_user_id(update)
    uname = (update.effective_user.username or "—") if update.effective_user else "—"
    await update.message.reply_text(
        f"Твой Telegram user id: {user_id}\n"
        f"(username: @{uname})\n\n"
        "Добавь в .env: TELEGRAM_ALLOWED_IDS=" + str(user_id)
    )


def _run_backtest_phases_and_chart():
    """Синхронно: бэктест фаз + построение графика. Возвращает (bytes_io, caption) или (None, error_text). Используется весь период из БД (max_bars=None)."""
    try:
        from ..utils.backtest_chart import build_phases_chart
    except ImportError as e:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    data = run_for_chart(timeframe="60", max_bars=None, step=5, min_score=0.0)
    if not data:
        return None, "Недостаточно данных в БД для бэктеста (нужны свечи по ТФ 60)."
    try:
        buf = build_phases_chart(data, dpi=120)
        stats = data.get("stats") or {}
        acc = stats.get("total_accuracy", 0) * 100
        total_n = stats.get("total_n", 0)
        symbol = stats.get("symbol", config.SYMBOL)
        bars_used = data.get("bars_used")
        period_str = f"{bars_used} свечей" if bars_used is not None else ""
        caption = f"Бэктест фаз | {symbol} ТФ 60 | весь период ({period_str}) | Точность: {acc:.1f}% (n={total_n})"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения графика бэктеста: %s", e)
        return None, f"Ошибка построения графика: {e}"


async def cmd_backtest_phases(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("typing")
    buf, caption = await asyncio.to_thread(_run_backtest_phases_and_chart)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


def _run_candlestick_chart(db_conn: sqlite3.Connection | None, symbol: str | None = None, timeframe: str = "D", lookback: int = 100, show_trends: bool = False):
    """Синхронно: при необходимости догружает ТФ до текущей даты, затем строит свечной график по всем свечам из БД (по максимуму). Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_candlestick_trend_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    conn = db_conn or get_connection()
    if conn is None:
        return None, "БД недоступна (TIMEFRAMES_DB пуст)."
    symbol = symbol or config.SYMBOL
    min_candles = (lookback + 1) if show_trends else 2
    try:
        candles = db_helper.ensure_fresh_then_get_all(conn, symbol, timeframe, max_lag_sec=86400, use_cache=True)
    finally:
        if conn is not db_conn:
            conn.close()
    if not candles or len(candles) < min_candles:
        return None, f"Недостаточно свечей в БД для графика (нужно минимум {min_candles}, есть {len(candles) if candles else 0}). Запустите accumulate_db.py."
    try:
        n = len(candles)
        buf = build_candlestick_trend_chart(
            candles, symbol, timeframe, lookback=lookback, show_trends=show_trends, max_candles_display=n, dpi=120
        )
        tf_label = _tf_label(timeframe)
        from datetime import datetime
        def _ts_to_date(ts):
            s = ts / 1000 if ts > 1e10 else ts
            return datetime.utcfromtimestamp(s).strftime("%d.%m.%Y")
        date_first = _ts_to_date(candles[0]["start_time"]) if candles else "—"
        date_last = _ts_to_date(candles[-1]["start_time"]) if candles else "—"
        caption = (
            f"Свечной график | {symbol} ТФ {tf_label} | все {n} свечей из БД\n"
            f"Период: {date_first} — {date_last}"
            + (" | Тренды (Вверх / Вниз / Флэт)" if show_trends else "")
        )
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения свечного графика: %s", e)
        return None, f"Ошибка построения графика: {e}"


async def cmd_chart(update, context) -> None:
    """Команда /chart: свечной график из БД (по умолчанию ТФ D, последние 2 года ≈ 730 свечей). Без зон трендов — только свечи."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("typing")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    buf, caption = await asyncio.to_thread(_run_candlestick_chart, db_conn, None, "D", 100)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


def _run_trend_daily_full(db_conn: sqlite3.Connection | None):
    """Синхронно: загружает все D-свечи из БД, строит график тренда по всей истории. Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_daily_trend_full_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    conn = db_conn or get_connection()
    if conn is None:
        return None, "БД недоступна."
    symbol = config.SYMBOL or "BTCUSDT"
    try:
        cur = conn.cursor()
        candles = get_candles(cur, symbol=symbol, timeframe="D", limit=None, order_asc=True)
    finally:
        if conn is not db_conn:
            conn.close()
    if not candles or len(candles) < 101:
        return None, f"Недостаточно свечей ТФ D в БД (нужно минимум 101, есть {len(candles) if candles else 0}). Запустите bin/accumulate_db.py или bin/refill_tf_d.py."
    try:
        buf = build_daily_trend_full_chart(candles, symbol, lookback=100, max_candles_display=2000, dpi=120)
        n_total = len(candles)
        n_display = min(n_total, 2000)
        caption = f"Тренд по всей БД ТФ D | {symbol}\nНа графике: последние {n_display} из {n_total} свечей (зоны Вверх / Вниз / Флэт)"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения графика тренда по БД: %s", e)
        return None, f"Ошибка построения графика: {e}"


def _run_trend_backtest(db_conn: sqlite3.Connection | None, timeframe: str = "60"):
    """Синхронно: бэктест тренда по всей БД (detect_trend vs форвард-доходность), строит график точности по направлениям. Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_trend_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    data = backtest_trend.run_for_chart(
        symbol=config.SYMBOL or None,
        timeframe=timeframe,
        max_bars=None,
        lookback=100,
        forward_bars=20,
        step=5,
        threshold_up=0.005,
        threshold_down=-0.005,
        min_strength=0.0,
    )
    if not data:
        return None, f"Недостаточно данных в БД для бэктеста тренда (нужны свечи по ТФ {timeframe}). Запустите bin/accumulate_db.py."
    try:
        buf = build_trend_chart(data, dpi=120)
        stats = data.get("stats") or {}
        acc = stats.get("total_accuracy", 0.0) * 100
        total_n = stats.get("total_n", 0)
        symbol = stats.get("symbol", config.SYMBOL)
        bars_used = data.get("bars_used")
        period_str = f"{bars_used} свечей" if bars_used is not None else ""
        tf_label = _tf_label(timeframe)
        caption = f"Бэктест тренда по всей БД | {symbol} ТФ {tf_label}\nТочность по направлению: {acc:.1f}% (n={total_n}), {period_str}"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения графика бэктеста тренда: %s", e)
        return None, f"Ошибка построения графика: {e}"


def _run_trade_2025_chart(year: int = 2025, initial_deposit: float = 100.0):
    """Синхронно: бэктест сценария управления сделкой по всем ТФ за год, строит график PnL и итог (старт $100). Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..scripts.backtest_trade_2025 import run_all_tf_for_chart
        from ..utils.backtest_chart import build_trade_2025_chart
    except ImportError as e:
        return None, f"Для графика нужны модули: {e}"
    try:
        results = run_all_tf_for_chart(
            year=year,
            symbol=config.SYMBOL,
            tp_sl_mode="trailing",
            initial_deposit=initial_deposit,
        )
        if not results:
            return None, f"За {year} год нет данных ни по одному ТФ. Запустите bin/accumulate_db.py."
        buf, caption = build_trade_2025_chart(results, year=year, initial_deposit=initial_deposit, dpi=120)
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка бэктеста trade_2025: %s", e)
        return None, f"Ошибка: {e}"


def _run_phase_chart(db_conn: sqlite3.Connection | None, symbol: str | None = None, timeframe: str = "D"):
    """Синхронно: загружает все свечи ТФ из БД (по максимуму), при необходимости догружает до актуальности, строит график с зонами 6 фаз. Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_candlestick_phase_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    conn = db_conn or get_connection()
    if conn is None:
        return None, "БД недоступна."
    symbol = symbol or config.SYMBOL or "BTCUSDT"
    try:
        if db_helper.is_stale(conn, symbol, timeframe, max_lag_sec=86400):
            db_helper.catch_up_tf(conn, symbol, timeframe)
        cur = conn.cursor()
        candles = get_candles(cur, symbol, timeframe, limit=None, order_asc=True)
    except Exception as e:
        logger.exception("Ошибка загрузки свечей для графика фаз: %s", e)
        return None, f"Ошибка загрузки данных: {e}"
    if not candles or len(candles) < 101:
        return None, f"Недостаточно свечей ТФ {timeframe} в БД (нужно минимум 101, есть {len(candles) if candles else 0}). Запустите bin/accumulate_db.py или bin/refill_tf_d.py."
    try:
        n = len(candles)
        buf = build_candlestick_phase_chart(
            candles, symbol, timeframe,
            lookback=100, max_candles_display=n, dpi=120,
        )
        first_ts = candles[0]["start_time"]
        last_ts = candles[-1]["start_time"]
        first_sec = first_ts / 1000 if first_ts > 1e10 else first_ts
        last_sec = last_ts / 1000 if last_ts > 1e10 else last_ts
        from datetime import datetime
        period_str = f"{datetime.utcfromtimestamp(first_sec).strftime('%d.%m.%Y')} – {datetime.utcfromtimestamp(last_sec).strftime('%d.%m.%Y')}"
        caption = f"6 фаз рынка | {symbol} ТФ {timeframe}\nНа графике: все {n} свечей из БД ({period_str})"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения графика фаз: %s", e)
        return None, f"Ошибка построения графика: {e}"


def _run_zones_chart(db_conn: sqlite3.Connection | None):
    """Синхронно: загружает все D-свечи из БД, строит график торговых зон (свечи + уровни поддержки/сопротивления). Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_candlestick_zones_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    conn = db_conn or get_connection()
    if conn is None:
        return None, "БД недоступна."
    symbol = config.SYMBOL or "BTCUSDT"
    try:
        cur = conn.cursor()
        candles = get_candles(cur, symbol=symbol, timeframe="D", limit=None, order_asc=True)
    finally:
        if conn is not db_conn:
            conn.close()
    if not candles or len(candles) < 50:
        return None, f"Недостаточно свечей ТФ D в БД (нужно минимум 50, есть {len(candles) if candles else 0}). Запустите bin/accumulate_db.py или bin/refill_tf_d.py."
    try:
        zones_max = getattr(config, "TRADING_ZONES_MAX_LEVELS", 0)
        max_levels_arg = None if zones_max <= 0 else zones_max
        buf = build_candlestick_zones_chart(
            candles, symbol,
            max_candles_display=2000,
            max_levels=max_levels_arg,
            max_levels_draw=24,
            dpi=120,
        )
        n_total = len(candles)
        n_display = min(n_total, 2000)
        caption = f"Торговые зоны по всей БД ТФ D | {symbol}\nНа графике: последние {n_display} из {n_total} свечей, уровни поддержки/сопротивления"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения графика торговых зон: %s", e)
        return None, f"Ошибка построения графика: {e}"


# 2 недели на ТФ 1ч: 14 дней * 24 = 336 свечей
ZONES_1H_LAST_WEEKS = 2
ZONES_1H_BARS = 14 * 24  # 336


def _run_zones_chart_1h(db_conn: sqlite3.Connection | None):
    """Синхронно: загружает последние 2 недели свечей ТФ 1ч, строит график торговых зон. Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_candlestick_zones_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    conn = db_conn or get_connection()
    if conn is None:
        return None, "БД недоступна."
    symbol = config.SYMBOL or "BTCUSDT"
    try:
        cur = conn.cursor()
        candles = get_candles(cur, symbol=symbol, timeframe="60", limit=ZONES_1H_BARS, order_asc=False)
    finally:
        if conn is not db_conn:
            conn.close()
    if not candles or len(candles) < 50:
        return None, f"Недостаточно свечей ТФ 1ч в БД (нужно минимум 50, есть {len(candles) if candles else 0}). Запустите bin/accumulate_db.py."
    try:
        zones_max = getattr(config, "TRADING_ZONES_MAX_LEVELS", 0)
        max_levels_arg = None if zones_max <= 0 else zones_max
        buf = build_candlestick_zones_chart(
            candles, symbol,
            max_candles_display=len(candles),
            max_levels=max_levels_arg,
            max_levels_draw=24,
            dpi=120,
            timeframe_label="1 ч",
        )
        n = len(candles)
        caption = f"Торговые зоны | {symbol} ТФ 1 ч | последние {ZONES_1H_LAST_WEEKS} нед. ({n} свечей)"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения графика торговых зон 1ч: %s", e)
        return None, f"Ошибка построения графика: {e}"


async def cmd_phases(update, context) -> None:
    """Команда /phases: свечной график с зонами 6 фаз рынка (Накопление, Рост, Распределение, Падение, Капитуляция, Восстановление)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("upload_photo")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    buf, caption = await asyncio.to_thread(_run_phase_chart, db_conn, None, "D")
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def cmd_zones_chart(update, context) -> None:
    """Команда /zones_chart: график торговых зон по всей БД ТФ D (свечи + уровни поддержки/сопротивления)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("upload_photo")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    buf, caption = await asyncio.to_thread(_run_zones_chart, db_conn)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def cmd_zones_1h(update, context) -> None:
    """Команда /zones_1h: график торговых зон на ТФ 1 ч за последние 2 недели."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("upload_photo")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    buf, caption = await asyncio.to_thread(_run_zones_chart_1h, db_conn)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def cmd_trend_daily(update, context) -> None:
    """Команда /trend_daily: тренд по всей БД на таймфрейме D с визуализацией (зоны Вверх / Вниз / Флэт)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("upload_photo")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    buf, caption = await asyncio.to_thread(_run_trend_daily_full, db_conn)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def cmd_trend_backtest(update, context) -> None:
    """Команда /trend_backtest: бэктест тренда по всей БД — график точности по направлениям (Вверх/Вниз/Флэт)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("upload_photo")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    # ТФ из аргумента команды, например /trend_backtest D или /trend_backtest 60
    timeframe = "60"
    if context and context.args:
        timeframe = (context.args[0] or "60").strip().upper()
    buf, caption = await asyncio.to_thread(_run_trend_backtest, db_conn, timeframe)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def cmd_trade_2025(update, context) -> None:
    """Команда /trade_2025: бэктест сценария управления сделкой по всем ТФ за год — график PnL и итог (старт $100)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("upload_photo")
    year = 2025
    if context and context.args:
        try:
            year = int(context.args[0])
        except (ValueError, IndexError):
            pass
    initial_deposit = 100.0
    buf, caption = await asyncio.to_thread(_run_trade_2025_chart, year, initial_deposit)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def handle_callback(update, context) -> None:
    """Обработка нажатий inline-кнопок."""
    q = update.callback_query
    try:
        await q.answer()
    except Exception as e:
        if BadRequest is not None and isinstance(e, BadRequest):
            logger.debug("Callback query устарел или недействителен: %s", e)
        else:
            raise
    user_id = q.from_user.id if q.from_user else 0
    if not _check_allowed(user_id):
        try:
            await q.edit_message_text("Доступ запрещён.")
        except Exception:
            await context.bot.send_message(chat_id=q.message.chat.id, text="Доступ запрещён.")
        return
    chat = q.message.chat
    bot = context.bot
    data = q.data
    if data == CB_SIGNAL:
        await _reply_signal(chat, bot, context=context, send_action=True)
    elif data == CB_ZONES:
        await _reply_zones(chat, bot, context=context, send_action=True)
    elif data == CB_MOMENTUM:
        await _reply_momentum(chat, bot, context=context, send_action=True)
    elif data == CB_DB:
        await _reply_db(chat, bot, send_action=True)
    elif data == CB_SANDBOX:
        await _reply_sandbox(chat, bot, context=context, send_action=True)
    elif data == CB_REFRESH_SANDBOX:
        try:
            await q.edit_message_text("Обновляю песочницу…")
        except Exception:
            pass
        await _reply_sandbox(chat, bot, context=context, send_action=False)
        try:
            await q.message.delete()
        except Exception:
            pass
    elif data == CB_SANDBOX_LOGS:
        try:
            await q.edit_message_text("Выгружаю логи песочницы…")
        except Exception:
            pass
        await _send_sandbox_logs(chat.id, bot, message_for_action=q.message)
        try:
            await q.answer()
        except Exception:
            pass
    elif data == CB_REFRESH_SIGNAL:
        try:
            await q.edit_message_text("Обновляю сигнал…")
        except Exception:
            pass
        await _reply_signal(chat, bot, context=context, send_action=False)
        try:
            await q.message.delete()
        except Exception:
            pass
    elif data == CB_REFRESH_ZONES:
        try:
            await q.edit_message_text("Обновляю зоны…")
        except Exception:
            pass
        await _reply_zones(chat, bot, context=context, send_action=False)
        try:
            await q.message.delete()
        except Exception:
            pass
    elif data == CB_REFRESH_MOMENTUM:
        try:
            await q.edit_message_text("Обновляю импульс…")
        except Exception:
            pass
        await _reply_momentum(chat, bot, context=context, send_action=False)
        try:
            await q.message.delete()
        except Exception:
            pass
    elif data == CB_REFRESH_DB:
        try:
            await q.edit_message_text("Обновляю БД…")
        except Exception:
            pass
        await _reply_db(chat, bot, send_action=False)
        try:
            await q.message.delete()
        except Exception:
            pass


async def handle_keyboard_button(update, context) -> None:
    """Обработка нажатий кнопок нижней панели (Reply)."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text == BTN_SIGNAL:
        await cmd_signal(update, context)
    elif text == BTN_DB:
        await cmd_db(update, context)
    elif text == BTN_ID:
        await cmd_id(update, context)
    elif text == BTN_HELP:
        await cmd_help(update, context)
    elif text == BTN_HIDE:
        if ReplyKeyboardRemove is not None:
            await update.message.reply_text(
                "Панель скрыта. /start — показать снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await update.message.reply_text("Панель скрыта. /start — показать снова.")


def run_bot(db_conn: sqlite3.Connection | None = None) -> None:
    """
    Запуск поллинга Telegram-бота. Один экземпляр на один токен.

    db_conn: если передан (например из main.py), используется общее соединение с БД,
    обновление БД не запускается (им управляет основной бот), в finally соединение не закрывается.
    Если None — вызывается open_and_prepare(), запускается периодическое обновление БД, в finally — close().
    """
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. "
            "Создай бота в Telegram через @BotFather, скопируй токен в .env: TELEGRAM_BOT_TOKEN=твой_токен"
        )

    # В потоке без своего event loop APScheduler/get_event_loop() падают (Python 3.10+).
    # Устанавливаем loop для текущего потока, если его ещё нет.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    import pytz
    import apscheduler.util as _aps_util
    _orig_astimezone = _aps_util.astimezone
    def _astimezone_pytz(obj):
        if obj is None:
            return None
        try:
            return _orig_astimezone(obj)
        except TypeError:
            return pytz.UTC
    _aps_util.astimezone = _astimezone_pytz

    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    from telegram.error import Conflict

    async def _on_error(update, context) -> None:
        err = context.error
        if isinstance(err, Conflict):
            logger.error(
                "Conflict: с этим токеном уже запущен другой бот или экземпляр. "
                "Остановите все остальные процессы с этим ботом и перезапустите один раз."
            )
            context.application.stop_running()
            return
        logger.exception("Необработанное исключение: %s", err)

    async def _post_init(app) -> None:
        if BotCommand is not None:
            await app.bot.set_my_commands([
                BotCommand("start", "Старт и панель"),
                BotCommand("signal", "Сигнал, фазы, зоны, импульс"),
                BotCommand("status", "Краткий статус (одна строка)"),
                BotCommand("sandbox", "Песочница микроструктуры (реальное время)"),
                BotCommand("zones", "Торговые зоны: поддержка/сопротивление (текст)"),
                BotCommand("zones_chart", "График торговых зон по всей БД ТФ D"),
                BotCommand("zones_1h", "Торговые зоны ТФ 1 ч за 2 нед."),
                BotCommand("momentum", "Импульс: RSI, состояние, направление"),
                BotCommand("db", "Статистика БД"),
                BotCommand("health", "Свежесть БД по ТФ"),
                BotCommand("backtest_phases", "График бэктеста фаз"),
                BotCommand("chart", "Свечной график: тренды Вверх/Вниз/Флэт"),
                BotCommand("phases", "График 6 фаз рынка"),
                BotCommand("trend_daily", "Тренд по всей БД ТФ D"),
                BotCommand("trend_backtest", "Бэктест тренда по всей БД (график точности)"),
                BotCommand("trade_2025", "Бэктест по ТФ за год: PnL и итог (старт $100)"),
                BotCommand("id", "Мой user id"),
                BotCommand("help", "Помощь"),
            ])

    # Таймауты запросов к Telegram API, чтобы команды (в т.ч. /sandbox) не зависали на минуты
    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .read_timeout(15.0)
        .write_timeout(15.0)
        .connect_timeout(10.0)
        .post_init(_post_init)
        .build()
    )
    app.add_error_handler(_on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("db", cmd_db))
    app.add_handler(CommandHandler("zones", cmd_zones))
    app.add_handler(CommandHandler("zones_chart", cmd_zones_chart))
    app.add_handler(CommandHandler("zones_1h", cmd_zones_1h))
    app.add_handler(CommandHandler("momentum", cmd_momentum))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("sandbox", cmd_sandbox))
    app.add_handler(CommandHandler("sandbox_logs", cmd_sandbox_logs))
    app.add_handler(CommandHandler("backtest_phases", cmd_backtest_phases))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("phases", cmd_phases))
    app.add_handler(CommandHandler("trend_daily", cmd_trend_daily))
    app.add_handler(CommandHandler("trend_backtest", cmd_trend_backtest))
    app.add_handler(CommandHandler("trade_2025", cmd_trade_2025))
    app.add_handler(CommandHandler("id", cmd_id))

    app.add_handler(CallbackQueryHandler(handle_callback))

    btn_filter = filters.Regex(
        f"^({BTN_SIGNAL}|{BTN_DB}|{BTN_ID}|{BTN_HELP}|{BTN_HIDE})$"
    )
    app.add_handler(MessageHandler(filters.TEXT & btn_filter, handle_keyboard_button))

    own_conn = False
    if db_conn is None:
        db_conn = open_and_prepare()
        own_conn = True
    app.bot_data["db_conn"] = db_conn
    app.bot_data["last_signal_direction"] = "none"
    if db_conn is not None and own_conn:
        last_db_ts: list[float] = [time.time()]

        async def _db_refresh_job(context) -> None:
            last_db_ts[0] = await asyncio.to_thread(refresh_if_due, db_conn, last_db_ts[0])

        app.job_queue.run_repeating(
            _db_refresh_job,
            interval=config.DB_UPDATE_INTERVAL_SEC,
            first=min(10, max(1, int(config.DB_UPDATE_INTERVAL_SEC))),
        )
        logger.info("БД будет обновляться каждые %s с", config.DB_UPDATE_INTERVAL_SEC)
    elif db_conn is None:
        logger.info("TIMEFRAMES_DB пуст — обновление БД отключено")

    # Алерт при смене сигнала: раз в N сек проверяем direction, при смене шлём в TELEGRAM_ALERT_CHAT_ID
    alert_chat_id = getattr(config, "TELEGRAM_ALERT_CHAT_ID", None)
    alert_on_change = getattr(config, "TELEGRAM_ALERT_ON_SIGNAL_CHANGE", False)
    alert_interval = getattr(config, "TELEGRAM_ALERT_INTERVAL_SEC", 90.0) or 90.0
    alert_min_conf = getattr(config, "TELEGRAM_ALERT_MIN_CONFIDENCE", 0.0) or 0.0
    if alert_chat_id and alert_on_change and app.job_queue:

        async def _alert_on_signal_change_job(context) -> None:
            conn = context.application.bot_data.get("db_conn")
            try:
                r = await asyncio.to_thread(analyze_multi_timeframe, db_conn=conn)
            except Exception as e:
                logger.warning("Алерт-проверка сигнала: %s", e)
                return
            direction = (r.get("signals") or {}).get("direction") or "none"
            confidence = (r.get("signals") or {}).get("confidence") or 0.0
            last = context.application.bot_data.get("last_signal_direction", "none")
            context.application.bot_data["last_signal_direction"] = direction
            if direction == last:
                return
            if confidence < alert_min_conf:
                return
            emoji = DIR_EMOJI.get(direction, direction.upper())
            phase_ru = r.get("higher_tf_phase_ru") or "—"
            text = f"{emoji} Смена сигнала: {direction.upper()} | {config.SYMBOL} | фаза {phase_ru} | уверенность {confidence:.2f}"
            try:
                await context.bot.send_message(chat_id=alert_chat_id, text=text)
            except Exception as e:
                logger.warning("Не удалось отправить алерт в %s: %s", alert_chat_id, e)

        app.job_queue.run_repeating(
            _alert_on_signal_change_job,
            interval=alert_interval,
            first=min(30, max(10, int(alert_interval))),
        )
        logger.info("Алерты при смене сигнала: каждые %s с в чат %s", alert_interval, alert_chat_id)

    logger.info("Telegram-бот запущен. Остановка: Ctrl+C.")
    try:
        app.run_polling(allowed_updates=["message", "callback_query"])
    finally:
        if own_conn:
            close(db_conn)
