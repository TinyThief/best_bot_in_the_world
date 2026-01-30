"""
Управление ботом через Telegram.
Команды: /start, /help, /signal, /status, /db, /backtest_phases, /chart, /id.
Reply-панель + inline-кнопки под сообщениями (Сигнал | БД | Обновить).
Запуск: python telegram_bot.py (launcher в корне).
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

from ..core import config
from ..core.database import get_candles, get_connection, get_db_path, count_candles
from ..analysis.multi_tf import analyze_multi_timeframe
from ..scripts.backtest_phases import run_for_chart
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
except ImportError:
    BotCommand = InlineKeyboardButton = InlineKeyboardMarkup = None  # type: ignore
    KeyboardButton = ReplyKeyboardMarkup = ReplyKeyboardRemove = None  # type: ignore

logger = logging.getLogger(__name__)

# Эмодзи по направлению сигнала
DIR_EMOJI = {"long": "🟢 Long", "short": "🔴 Short", "none": "⚪ None"}

HELP_TEXT = """Команды:
/signal — полный разбор: сигнал и фазы по таймфреймам
/status — одна строка: сигнал и старший таймфрейм
/db — статистика базы свечей
/backtest_phases — график бэктеста фаз (весь период из БД)
/chart — свечной график с трендами Вверх / Вниз / Флэт (из БД)
/id — твой Telegram user id (для TELEGRAM_ALLOWED_IDS)
/help — это сообщение"""

# Кнопки нижней панели (Reply)
BTN_SIGNAL = "📊 Сигнал"
BTN_DB = "🗄 БД"
BTN_ID = "🆔 Мой ID"
BTN_HELP = "❓ Помощь"
BTN_HIDE = "⬇ Скрыть панель"

# Callback data для inline-кнопок
CB_SIGNAL = "cb_signal"
CB_DB = "cb_db"
CB_REFRESH_SIGNAL = "cb_refresh_signal"
CB_REFRESH_DB = "cb_refresh_db"

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
            "",
            f"Старший ТФ ({higher_label}): тренд {r.get('higher_tf_trend', '?')} ({r.get('higher_tf_trend_ru', '—')}), фаза {r.get('higher_tf_phase_ru', '—')}",
        ]
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


def _inline_actions_keyboard(kind: str):
    """Inline-кнопки под сообщением: Обновить + переключение Сигнал/БД."""
    if InlineKeyboardButton is None or InlineKeyboardMarkup is None:
        return None
    if kind == "signal":
        row = [
            InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_SIGNAL),
            InlineKeyboardButton("🗄 БД", callback_data=CB_DB),
        ]
    else:
        row = [
            InlineKeyboardButton("🔄 Обновить", callback_data=CB_REFRESH_DB),
            InlineKeyboardButton("📊 Сигнал", callback_data=CB_SIGNAL),
        ]
    return InlineKeyboardMarkup([row])


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
    await update.message.reply_text(text, reply_markup=markup)


async def cmd_help(update, context) -> None:
    user_id = _get_user_id(update)
    if not _check_allowed(user_id):
        await update.message.reply_text("Доступ запрещён.")
        return
    await update.message.reply_text(HELP_TEXT)


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


async def cmd_db(update, context) -> None:
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    await _reply_db(update.message, context.bot)


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


def _run_candlestick_chart(db_conn: sqlite3.Connection | None, symbol: str | None = None, timeframe: str = "D", limit: int = 1500, lookback: int = 100):
    """Синхронно: загрузка свечей из БД + построение свечного графика с трендами (Вверх/Вниз/Флэт). Возвращает (bytes_io, caption) или (None, error_text)."""
    try:
        from ..utils.backtest_chart import build_candlestick_trend_chart
    except ImportError:
        return None, "Для графиков нужен matplotlib: pip install matplotlib"
    conn = db_conn or get_connection()
    if conn is None:
        return None, "БД недоступна (TIMEFRAMES_DB пуст)."
    symbol = symbol or config.SYMBOL
    try:
        cur = conn.cursor()
        # Последние limit свечей (от новых к старым в запросе, в списке — от старых к новым для графика)
        candles = get_candles(cur, symbol, timeframe, limit=limit, order_asc=False)
    finally:
        if conn is not db_conn:
            conn.close()
    if not candles or len(candles) < lookback + 1:
        return None, f"Недостаточно свечей в БД для графика (нужно минимум {lookback + 1}, есть {len(candles) if candles else 0}). Запустите accumulate_db.py."
    try:
        buf = build_candlestick_trend_chart(
            candles, symbol, timeframe, lookback=lookback, dpi=120
        )
        tf_label = _tf_label(timeframe)
        caption = f"Свечной график | {symbol} ТФ {tf_label} | Тренды (Вверх / Вниз / Флэт) | {len(candles)} свечей"
        return buf, caption
    except Exception as e:
        logger.exception("Ошибка построения свечного графика: %s", e)
        return None, f"Ошибка построения графика: {e}"


async def cmd_chart(update, context) -> None:
    """Команда /chart: свечной график с трендами (Вверх/Вниз/Флэт) из БД (по умолчанию ТФ D, до 1500 свечей)."""
    if not _check_allowed(_get_user_id(update)):
        await update.message.reply_text("Доступ запрещён.")
        return
    if hasattr(update.message, "reply_chat_action"):
        await update.message.reply_chat_action("typing")
    db_conn = (context.bot_data.get("db_conn") if context and context.bot_data else None) or None
    buf, caption = await asyncio.to_thread(_run_candlestick_chart, db_conn, None, "D", 1500, 100)
    if buf is None:
        await update.message.reply_text(caption)
        return
    buf.seek(0)
    await update.message.reply_photo(photo=buf, caption=caption[:1024])


async def handle_callback(update, context) -> None:
    """Обработка нажатий inline-кнопок."""
    q = update.callback_query
    await q.answer()
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
    elif data == CB_DB:
        await _reply_db(chat, bot, send_action=True)
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
                BotCommand("signal", "Сигнал и фазы по таймфреймам"),
                BotCommand("status", "Краткий статус (одна строка)"),
                BotCommand("db", "Статистика БД"),
                BotCommand("backtest_phases", "График бэктеста фаз"),
                BotCommand("chart", "Свечной график: тренды Вверх/Вниз/Флэт"),
                BotCommand("id", "Мой user id"),
                BotCommand("help", "Помощь"),
            ])

    app = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )
    app.add_error_handler(_on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("db", cmd_db))
    app.add_handler(CommandHandler("backtest_phases", cmd_backtest_phases))
    app.add_handler(CommandHandler("chart", cmd_chart))
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

    logger.info("Telegram-бот запущен. Остановка: Ctrl+C.")
    try:
        app.run_polling(allowed_updates=["message", "callback_query"])
    finally:
        if own_conn:
            close(db_conn)
