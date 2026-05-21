"""
bot.py — Jorge Stock Scanner Bot
══════════════════════════════════
Bot de Telegram que escanea el mercado de acciones
usando Yahoo Finance + Claude AI.

Comandos:
  /scan    — Escanea todo el watchlist ahora
  /top     — Top 5 oportunidades del momento
  /analyze AAPL — Analiza un stock específico
  /add AAPL    — Agrega al watchlist
  /list        — Ver watchlist actual
  /help        — Ayuda
"""

import os
import logging
import asyncio
from datetime import time as dtime
import pytz

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters,
)
from telegram.constants import ParseMode

import config
from scanner import scan_stocks, fetch_stock_data, score_stock, calc_levels
from ai_analyst import analyze_stock_with_claude, format_stock_alert

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Runtime watchlist (modifiable per session) ────────────────
_watchlist = list(config.WATCHLIST)

ET = pytz.timezone("America/New_York")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

async def send_startup_message(app: Application):
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return
    await app.bot.send_message(
        chat_id=chat_id,
        text=(
            "📈 <b>Jorge Stock Scanner — Online</b>\n\n"
            f"✅ Watchlist: {len(_watchlist)} acciones\n"
            "🤖 Claude AI: Activo\n"
            "⏰ Scan automático: cada hora en horario de mercado\n\n"
            "Usa /scan para escanear ahora o /help para ver comandos."
        ),
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 <b>Jorge Stock Scanner</b>\n\n"
        "/scan — Escanear todo el watchlist\n"
        "/top — Top 5 oportunidades ahora\n"
        "/analyze AAPL — Analizar un stock\n"
        "/add AAPL — Agregar al watchlist\n"
        "/remove AAPL — Quitar del watchlist\n"
        "/list — Ver watchlist\n"
        "/earnings — Próximos earnings del watchlist\n"
        "/help — Esta ayuda",
        parse_mode=ParseMode.HTML,
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(
        f"🔍 Escaneando {len(_watchlist)} acciones con Claude AI... espera ~30 seg."
    )
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: scan_stocks(_watchlist, config.MIN_SCORE)
    )

    if not results:
        await msg.edit_text("😴 No hay oportunidades claras ahora. Mercado lateral.")
        return

    await msg.edit_text(f"✅ {len(results)} oportunidades encontradas. Enviando alertas...")

    for stock in results[:8]:  # Max 8 alerts per scan
        ai = await asyncio.get_event_loop().run_in_executor(
            None, lambda s=stock: analyze_stock_with_claude(s)
        )
        text = format_stock_alert(stock, ai)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.5)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Buscando top 5 oportunidades...")
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: scan_stocks(_watchlist, min_score=60)
    )

    if not results:
        await msg.edit_text("😴 Sin señales claras ahora.")
        return

    top5 = results[:5]
    lines = ["🏆 <b>TOP 5 OPORTUNIDADES</b>\n"]
    for i, s in enumerate(top5, 1):
        arrow = "🟢" if s["direction"] == "LONG" else "🔴"
        lines.append(
            f"{i}. {arrow} <b>{s['symbol']}</b> ${s['price']} "
            f"| Score: {s['score']} | {s['chg_1d']:+.1f}% hoy"
        )

    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Uso: /analyze AAPL")
        return

    symbol = args[0].upper().strip()
    msg = await update.message.reply_text(f"🔍 Analizando {symbol} con Claude AI...")

    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: fetch_stock_data(symbol)
    )
    if not data:
        await msg.edit_text(f"❌ No pude obtener datos para {symbol}. ¿Es un ticker válido?")
        return

    score, direction, reasons = score_stock(data)
    levels = calc_levels(data, direction)
    stock = {**data, "score": score, "direction": direction, "reasons": reasons, **levels}

    ai = await asyncio.get_event_loop().run_in_executor(
        None, lambda: analyze_stock_with_claude(stock)
    )
    text = format_stock_alert(stock, ai)
    await msg.edit_text(text, parse_mode=ParseMode.HTML)


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Uso: /add AAPL")
        return
    sym = ctx.args[0].upper().strip()
    if sym not in _watchlist:
        _watchlist.append(sym)
        await update.message.reply_text(f"✅ {sym} agregado al watchlist ({len(_watchlist)} total)")
    else:
        await update.message.reply_text(f"⚠️ {sym} ya está en el watchlist")


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Uso: /remove AAPL")
        return
    sym = ctx.args[0].upper().strip()
    if sym in _watchlist:
        _watchlist.remove(sym)
        await update.message.reply_text(f"✅ {sym} removido del watchlist")
    else:
        await update.message.reply_text(f"⚠️ {sym} no está en el watchlist")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chunks = [_watchlist[i:i+10] for i in range(0, len(_watchlist), 10)]
    text   = f"📋 <b>Watchlist ({len(_watchlist)} stocks):</b>\n"
    for chunk in chunks:
        text += "  " + " · ".join(chunk) + "\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_earnings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show upcoming earnings for the watchlist."""
    msg = await update.message.reply_text("📅 Consultando earnings calendar...")
    try:
        from earnings_calendar import get_earnings_batch, format_earnings_calendar
        earnings_map = await asyncio.get_event_loop().run_in_executor(
            None, lambda: get_earnings_batch(_watchlist)
        )
        text = format_earnings_calendar(earnings_map)
        await msg.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────────────────────
# Scheduled jobs
# ─────────────────────────────────────────────────────────────

async def job_auto_scan(ctx: ContextTypes.DEFAULT_TYPE):
    """Auto-scan every hour during market hours (9:30–16:00 ET)."""
    now_et = asyncio.get_event_loop().time()
    # Simple market hours check via datetime
    from datetime import datetime
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Weekend
        return
    if not (9 <= now.hour < 16):  # Outside market hours
        return

    log.info("🔄 Auto-scan running...")
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: scan_stocks(_watchlist, config.MIN_SCORE)
    )

    if not results:
        return

    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    # Send top 3 best opportunities
    for stock in results[:3]:
        ai = await asyncio.get_event_loop().run_in_executor(
            None, lambda s=stock: analyze_stock_with_claude(s)
        )
        text = "🤖 <b>AUTO-SCAN</b>\n\n" + format_stock_alert(stock, ai)
        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        await asyncio.sleep(1)


async def job_daily_open(ctx: ContextTypes.DEFAULT_TYPE):
    """Daily scan at market open."""
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    from datetime import datetime
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return

    log.info("📈 Daily market open scan...")
    await ctx.bot.send_message(
        chat_id=chat_id,
        text="🔔 <b>Mercado abierto — Escaneando oportunidades del día...</b>",
        parse_mode=ParseMode.HTML,
    )

    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: scan_stocks(_watchlist, min_score=65)
    )

    if not results:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text="😴 Sin señales fuertes al abrir. Monitoreo activo.",
        )
        return

    for stock in results[:5]:
        ai = await asyncio.get_event_loop().run_in_executor(
            None, lambda s=stock: analyze_stock_with_claude(s)
        )
        text = "🌅 <b>APERTURA DEL MERCADO</b>\n\n" + format_stock_alert(stock, ai)
        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        await asyncio.sleep(1)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set!")

    log.info("🚀 Starting Jorge Stock Scanner Bot...")

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("start",   cmd_help))
    app.add_handler(CommandHandler("scan",    cmd_scan))
    app.add_handler(CommandHandler("top",     cmd_top))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("add",     cmd_add))
    app.add_handler(CommandHandler("remove",  cmd_remove))
    app.add_handler(CommandHandler("list",     cmd_list))
    app.add_handler(CommandHandler("earnings", cmd_earnings))

    # Scheduled jobs
    jq = app.job_queue
    # Auto-scan every 60 min
    jq.run_repeating(job_auto_scan, interval=3600, first=120)
    # Daily open scan at 9:35 AM ET
    jq.run_daily(
        job_daily_open,
        time=dtime(hour=9, minute=35, tzinfo=ET),
    )

    # Startup message
    app.post_init = lambda a: send_startup_message(a)

    log.info(f"✅ Bot running | Watchlist: {len(_watchlist)} stocks")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
