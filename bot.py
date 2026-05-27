"""
bot.py — Jorge Stock Scanner Bot
══════════════════════════════════
Bot de Telegram que escanea el mercado de acciones
usando Yahoo Finance + Claude AI.

Comandos:
  /scan          — Escanea todo el watchlist ahora
  /scan SEMIS    — Escanea un grupo específico
  /analyze AAPL  — Analiza un stock específico
  /compare NVDA AMD — Compara dos stocks con Claude AI
  /movers        — Top gainers y losers del watchlist hoy
  /brief         — Resumen rápido del mercado
  /alert NVDA 140  — Alerta cuando NVDA llegue a $140
  /alerts        — Ver alertas activas
  /delalert NVDA — Eliminar alerta
  /groups        — Ver grupos disponibles del watchlist
  /add AAPL      — Agrega al watchlist (persiste)
  /list          — Ver watchlist actual
  /earnings      — Próximos earnings del watchlist
  /help          — Ayuda
"""

import os
import json
import logging
import asyncio
from datetime import time as dtime
from pathlib import Path
import pytz
import yfinance as yf

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters,
)
from telegram.constants import ParseMode

import config
from scanner import scan_stocks, fetch_stock_data, score_stock, calc_levels
from ai_analyst import analyze_stock_with_claude, format_stock_alert, compare_stocks_with_claude, format_compare_result

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# ── Watchlist persistente ─────────────────────────────────────
WATCHLIST_FILE = Path("watchlist.json")

def _load_watchlist() -> list:
    """Load watchlist from JSON file, fallback to config."""
    try:
        if WATCHLIST_FILE.exists():
            data = json.loads(WATCHLIST_FILE.read_text())
            if isinstance(data, list) and data:
                log.info(f"📋 Watchlist cargado desde archivo: {len(data)} stocks")
                return data
    except Exception as e:
        log.warning(f"Watchlist load error: {e}")
    return list(config.WATCHLIST)

def _save_watchlist(wl: list):
    """Persist watchlist to JSON file."""
    try:
        WATCHLIST_FILE.write_text(json.dumps(wl))
    except Exception as e:
        log.warning(f"Watchlist save error: {e}")

_watchlist = _load_watchlist()

# ── Price alerts ──────────────────────────────────────────────
# {symbol: {"target": float, "direction": "above"|"below", "chat_id": str}}
_alerts: dict = {}


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
            "⏰ Scan automático: cada hora en horario de mercado\n"
            "🌅 Pre-market: 8:30 AM ET\n"
            "🔔 Price alerts: activos\n\n"
            "Usa /scan para escanear ahora o /help para ver comandos."
        ),
        parse_mode=ParseMode.HTML,
    )

def _get_market_price(symbol: str) -> float | None:
    """Quick price fetch via yfinance info."""
    try:
        info = yf.Ticker(symbol).info
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 <b>Jorge Stock Scanner</b>\n\n"
        "/scan — Escanear todo el watchlist\n"
        "/scan SEMIS — Escanear un grupo (AI, SEMIS, BIGTECH…)\n"
        "/analyze AAPL — Analizar un stock con Claude AI\n"
        "/compare NVDA AMD — Comparar dos stocks\n"
        "/movers — Top gainers y losers del día\n"
        "/brief — Resumen rápido del mercado\n"
        "/alert NVDA 140 — Alerta de precio\n"
        "/alerts — Ver alertas activas\n"
        "/delalert NVDA — Eliminar alerta\n"
        "/groups — Ver grupos del watchlist\n"
        "/add AAPL — Agregar al watchlist\n"
        "/list — Ver watchlist\n"
        "/earnings — Próximos earnings\n"
        "/help — Esta ayuda",
        parse_mode=ParseMode.HTML,
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    group_name  = ctx.args[0].upper() if ctx.args else None
    target_list = _watchlist

    if group_name:
        groups = config.WATCHLIST_GROUPS
        if group_name not in groups:
            available = " · ".join(groups.keys())
            await update.message.reply_text(
                f"❌ Grupo <b>{group_name}</b> no existe.\n"
                f"Grupos disponibles: {available}",
                parse_mode=ParseMode.HTML,
            )
            return
        target_list = groups[group_name]
        label = f"grupo <b>{group_name}</b> ({len(target_list)} stocks)"
    else:
        label = f"<b>{len(target_list)} acciones</b> del watchlist"

    msg = await update.message.reply_text(
        f"🔍 Escaneando {label} con Claude AI... espera ~30 seg.",
        parse_mode=ParseMode.HTML,
    )
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: scan_stocks(target_list, config.MIN_SCORE)
    )

    if not results:
        await msg.edit_text("😴 No hay oportunidades claras ahora. Mercado lateral.")
        return

    await msg.edit_text(f"✅ {len(results)} oportunidades encontradas. Enviando alertas...")

    for stock in results[:8]:
        ai   = await asyncio.get_event_loop().run_in_executor(
            None, lambda s=stock: analyze_stock_with_claude(s)
        )
        text = format_stock_alert(stock, ai)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.5)


async def cmd_movers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Top gainers and losers from watchlist today."""
    msg = await update.message.reply_text("📊 Obteniendo movers del watchlist...")

    loop    = asyncio.get_event_loop()
    sample  = _watchlist[:20]  # top 20 for speed

    data_list = await loop.run_in_executor(
        None,
        lambda: [d for sym in sample if (d := fetch_stock_data(sym)) is not None]
    )

    if not data_list:
        await msg.edit_text("❌ No se pudieron obtener datos.")
        return

    sorted_by_chg = sorted(data_list, key=lambda x: x["chg_1d"], reverse=True)
    gainers = sorted_by_chg[:5]
    losers  = sorted_by_chg[-5:][::-1]

    lines = ["📊 <b>MOVERS DEL DÍA</b>\n"]

    lines.append("🟢 <b>Top Gainers</b>")
    for s in gainers:
        lines.append(f"  <b>{s['symbol']}</b> ${s['price']} | {s['chg_1d']:+.2f}% | Vol: {s['vol_ratio']}x")

    lines.append("\n🔴 <b>Top Losers</b>")
    for s in losers:
        lines.append(f"  <b>{s['symbol']}</b> ${s['price']} | {s['chg_1d']:+.2f}% | Vol: {s['vol_ratio']}x")

    lines.append(f"\n<i>Basado en {len(data_list)} stocks del watchlist</i>")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quick market summary: SPY, VIX, top movers, best opportunity."""
    msg = await update.message.reply_text("⚡ Generando briefing del mercado...")

    loop = asyncio.get_event_loop()

    def _fetch_brief():
        results = {}
        # SPY
        try:
            spy = yf.Ticker("SPY")
            si  = spy.info
            results["spy_price"] = si.get("currentPrice") or si.get("regularMarketPrice", 0)
            results["spy_chg"]   = si.get("regularMarketChangePercent", 0)
        except Exception:
            results["spy_price"] = results["spy_chg"] = 0

        # VIX
        try:
            vix = yf.Ticker("^VIX")
            vi  = vix.info
            results["vix"] = vi.get("currentPrice") or vi.get("regularMarketPrice", 0)
        except Exception:
            results["vix"] = 0

        # Top movers from watchlist (quick, no scoring)
        movers = []
        for sym in _watchlist[:15]:
            d = fetch_stock_data(sym)
            if d:
                movers.append(d)
        movers.sort(key=lambda x: x["chg_1d"], reverse=True)
        results["top_gainer"] = movers[0]  if movers else None
        results["top_loser"]  = movers[-1] if movers else None

        # Best opportunity (quick scan, top 1)
        opps = scan_stocks(_watchlist[:15], min_score=60)
        results["best_opp"] = opps[0] if opps else None

        return results

    r = await loop.run_in_executor(None, _fetch_brief)

    spy_arrow = "🟢" if r["spy_chg"] >= 0 else "🔴"
    vix_icon  = "😱" if r["vix"] > 25 else "😰" if r["vix"] > 20 else "😌"

    lines = [
        "⚡ <b>MARKET BRIEF</b>\n",
        f"{spy_arrow} <b>S&P 500 (SPY)</b> ${r['spy_price']:.2f} | {r['spy_chg']:+.2f}% hoy",
        f"{vix_icon} <b>VIX</b> {r['vix']:.1f} {'— Volatilidad alta ⚠️' if r['vix'] > 25 else '— Mercado tranquilo'}",
    ]

    if r["top_gainer"]:
        g = r["top_gainer"]
        lines.append(f"\n🥇 Mejor del día: <b>{g['symbol']}</b> {g['chg_1d']:+.2f}%")
    if r["top_loser"]:
        l = r["top_loser"]
        lines.append(f"📉 Peor del día:  <b>{l['symbol']}</b> {l['chg_1d']:+.2f}%")

    if r["best_opp"]:
        o = r["best_opp"]
        arrow = "🟢" if o["direction"] == "LONG" else "🔴"
        lines.append(f"\n🎯 Mejor setup: {arrow} <b>{o['symbol']}</b> score {o['score']}/100 | ${o['price']}")

    lines.append("\n<i>Usa /scan para análisis completo · /movers para ver todos</i>")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/alert NVDA 140 — notify when NVDA hits $140."""
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(
            "Uso: /alert NVDA 140\n"
            "Te aviso cuando NVDA llegue a $140 (arriba o abajo)."
        )
        return

    sym = ctx.args[0].upper().strip()
    try:
        target = float(ctx.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Precio inválido. Ej: /alert NVDA 140.50")
        return

    # Get current price to determine direction
    current = await asyncio.get_event_loop().run_in_executor(None, lambda: _get_market_price(sym))
    if not current:
        await update.message.reply_text(f"❌ No pude obtener precio de {sym}.")
        return

    direction = "above" if target > current else "below"
    _alerts[sym] = {
        "target":    target,
        "direction": direction,
        "chat_id":   update.effective_chat.id,
        "current":   current,
    }

    arrow = "⬆️" if direction == "above" else "⬇️"
    await update.message.reply_text(
        f"🔔 Alerta configurada:\n"
        f"<b>{sym}</b> {arrow} ${target} "
        f"(ahora: ${current})\n"
        f"Te aviso cuando llegue.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show active alerts."""
    if not _alerts:
        await update.message.reply_text("📭 No tienes alertas activas.\nUsa /alert NVDA 140 para crear una.")
        return

    lines = ["🔔 <b>Alertas activas</b>\n"]
    for sym, a in _alerts.items():
        arrow = "⬆️" if a["direction"] == "above" else "⬇️"
        lines.append(f"<b>{sym}</b> {arrow} ${a['target']} (entrada: ${a['current']})")

    lines.append(f"\n<i>Total: {len(_alerts)} alertas · /delalert NVDA para eliminar</i>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_delalert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Remove a price alert."""
    if not ctx.args:
        await update.message.reply_text("Uso: /delalert NVDA")
        return
    sym = ctx.args[0].upper().strip()
    if sym in _alerts:
        del _alerts[sym]
        await update.message.reply_text(f"✅ Alerta de {sym} eliminada.")
    else:
        await update.message.reply_text(f"⚠️ No hay alerta activa para {sym}.")


async def cmd_groups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["📂 <b>Grupos del Watchlist</b>\n"]
    for name, tickers in config.WATCHLIST_GROUPS.items():
        lines.append(f"<b>{name}</b> ({len(tickers)}) — {' · '.join(tickers)}")
    lines.append("\nUso: /scan AI · /scan SEMIS · /scan BIGTECH")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_compare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text("Uso: /compare NVDA AMD")
        return

    sym1 = ctx.args[0].upper().strip()
    sym2 = ctx.args[1].upper().strip()

    if sym1 == sym2:
        await update.message.reply_text("❌ Pon dos tickers diferentes.")
        return

    msg  = await update.message.reply_text(f"⚔️ Comparando {sym1} vs {sym2} con Claude AI...")
    loop = asyncio.get_event_loop()

    data1, data2 = await asyncio.gather(
        loop.run_in_executor(None, lambda: fetch_stock_data(sym1)),
        loop.run_in_executor(None, lambda: fetch_stock_data(sym2)),
    )

    if not data1:
        await msg.edit_text(f"❌ No pude obtener datos para {sym1}.")
        return
    if not data2:
        await msg.edit_text(f"❌ No pude obtener datos para {sym2}.")
        return

    score1, dir1, reasons1 = score_stock(data1)
    score2, dir2, reasons2 = score_stock(data2)
    s1 = {**data1, "score": score1, "direction": dir1, "reasons": reasons1, **calc_levels(data1, dir1)}
    s2 = {**data2, "score": score2, "direction": dir2, "reasons": reasons2, **calc_levels(data2, dir2)}

    ai   = await loop.run_in_executor(None, lambda: compare_stocks_with_claude(s1, s2))
    text = format_compare_result(s1, s2, ai)
    await msg.edit_text(text, parse_mode=ParseMode.HTML)


async def cmd_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Uso: /analyze AAPL")
        return

    symbol = ctx.args[0].upper().strip()
    msg    = await update.message.reply_text(f"🔍 Analizando {symbol} con Claude AI...")

    data = await asyncio.get_event_loop().run_in_executor(None, lambda: fetch_stock_data(symbol))
    if not data:
        await msg.edit_text(f"❌ No pude obtener datos para {symbol}. ¿Es un ticker válido?")
        return

    score, direction, reasons = score_stock(data)
    levels = calc_levels(data, direction)
    stock  = {**data, "score": score, "direction": direction, "reasons": reasons, **levels}

    ai   = await asyncio.get_event_loop().run_in_executor(None, lambda: analyze_stock_with_claude(stock))
    text = format_stock_alert(stock, ai)
    await msg.edit_text(text, parse_mode=ParseMode.HTML)


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Uso: /add AAPL")
        return
    sym = ctx.args[0].upper().strip()
    if sym not in _watchlist:
        _watchlist.append(sym)
        _save_watchlist(_watchlist)
        await update.message.reply_text(f"✅ {sym} agregado al watchlist ({len(_watchlist)} total) — guardado ✓")
    else:
        await update.message.reply_text(f"⚠️ {sym} ya está en el watchlist")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chunks = [_watchlist[i:i+10] for i in range(0, len(_watchlist), 10)]
    text   = f"📋 <b>Watchlist ({len(_watchlist)} stocks):</b>\n"
    for chunk in chunks:
        text += "  " + " · ".join(chunk) + "\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_earnings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

async def job_alert_checker(ctx: ContextTypes.DEFAULT_TYPE):
    """Check price alerts every 60 seconds."""
    if not _alerts:
        return

    triggered = []
    loop = asyncio.get_event_loop()

    for sym, alert in list(_alerts.items()):
        try:
            price = await loop.run_in_executor(None, lambda s=sym: _get_market_price(s))
            if price is None:
                continue

            hit = (
                (alert["direction"] == "above" and price >= alert["target"]) or
                (alert["direction"] == "below" and price <= alert["target"])
            )

            if hit:
                arrow = "⬆️" if alert["direction"] == "above" else "⬇️"
                await ctx.bot.send_message(
                    chat_id=alert["chat_id"],
                    text=(
                        f"🔔 <b>ALERTA ACTIVADA — {sym}</b>\n\n"
                        f"Precio actual: <b>${price}</b>\n"
                        f"Target: {arrow} ${alert['target']}\n\n"
                        f"Usa /analyze {sym} para análisis completo."
                    ),
                    parse_mode=ParseMode.HTML,
                )
                triggered.append(sym)
                log.info(f"🔔 Alert triggered: {sym} @ ${price}")
        except Exception as e:
            log.warning(f"Alert check error ({sym}): {e}")

    for sym in triggered:
        _alerts.pop(sym, None)


async def job_earnings_alert(ctx: ContextTypes.DEFAULT_TYPE):
    """Daily job: warn about earnings happening in ≤3 days."""
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    from datetime import datetime
    if datetime.now(ET).weekday() >= 5:
        return

    try:
        from earnings_calendar import get_earnings_batch
        earnings_map = await asyncio.get_event_loop().run_in_executor(
            None, lambda: get_earnings_batch(_watchlist)
        )
        upcoming = [
            (ticker, info) for ticker, info in earnings_map.items()
            if info.get("ok") and 1 <= info.get("days_away", 999) <= 3
        ]
        upcoming.sort(key=lambda x: x[1]["days_away"])

        if not upcoming:
            return

        lines = ["⚠️ <b>EARNINGS PRÓXIMOS — ALERTA</b>\n",
                 "Señales de estos stocks están <b>bloqueadas</b>.\n"]
        for ticker, info in upcoming:
            days = info["days_away"]
            icon = "🔴" if days == 1 else "🟡" if days == 2 else "🟠"
            lines.append(f"{icon} <b>{ticker}</b> — en <b>{days}d</b> ({info['date']})")

        lines.append("\n📌 Se desbloquean 1 día después del reporte.")
        await ctx.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode=ParseMode.HTML)

    except Exception as e:
        log.warning(f"job_earnings_alert error: {e}")


async def job_premarket_scan(ctx: ContextTypes.DEFAULT_TYPE):
    """Pre-market scan at 8:30 AM ET — gap ups/downs before open."""
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    from datetime import datetime
    if datetime.now(ET).weekday() >= 5:
        return

    log.info("🌄 Pre-market scan running...")

    def _fetch_premarket():
        movers = []
        for sym in _watchlist:
            try:
                info       = yf.Ticker(sym).info
                pre_price  = info.get("preMarketPrice")
                prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

                if not pre_price or not prev_close or prev_close == 0:
                    continue

                gap_pct = ((pre_price - prev_close) / prev_close) * 100

                if abs(gap_pct) >= 1.0:  # Solo gaps de ≥1%
                    movers.append({
                        "symbol":     sym,
                        "pre_price":  round(pre_price, 2),
                        "prev_close": round(prev_close, 2),
                        "gap_pct":    round(gap_pct, 2),
                    })
            except Exception:
                continue

        return sorted(movers, key=lambda x: abs(x["gap_pct"]), reverse=True)

    movers = await asyncio.get_event_loop().run_in_executor(None, _fetch_premarket)

    if not movers:
        await ctx.bot.send_message(
            chat_id=chat_id,
            text="🌄 Pre-market: Sin gaps significativos (>1%). Apertura tranquila.",
        )
        return

    gap_ups   = [m for m in movers if m["gap_pct"] > 0][:4]
    gap_downs = [m for m in movers if m["gap_pct"] < 0][:4]

    lines = ["🌄 <b>PRE-MARKET — GAPS DETECTADOS</b>\n"]

    if gap_ups:
        lines.append("⬆️ <b>Gap Up</b>")
        for m in gap_ups:
            lines.append(f"  <b>{m['symbol']}</b> ${m['pre_price']} | {m['gap_pct']:+.2f}% vs cierre")

    if gap_downs:
        lines.append("\n⬇️ <b>Gap Down</b>")
        for m in gap_downs:
            lines.append(f"  <b>{m['symbol']}</b> ${m['pre_price']} | {m['gap_pct']:+.2f}% vs cierre")

    lines.append(f"\n⏰ Mercado abre en ~1 hora · /analyze TICKER para análisis completo")
    await ctx.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode=ParseMode.HTML)


async def job_auto_scan(ctx: ContextTypes.DEFAULT_TYPE):
    """Auto-scan every hour during market hours (9:30–16:00 ET)."""
    from datetime import datetime
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return
    if not (9 <= now.hour < 16):
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

    for stock in results[:3]:
        ai   = await asyncio.get_event_loop().run_in_executor(
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
    if datetime.now(ET).weekday() >= 5:
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
        await ctx.bot.send_message(chat_id=chat_id, text="😴 Sin señales fuertes al abrir. Monitoreo activo.")
        return

    for stock in results[:5]:
        ai   = await asyncio.get_event_loop().run_in_executor(
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

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("start",    cmd_help))
    app.add_handler(CommandHandler("scan",     cmd_scan))
    app.add_handler(CommandHandler("analyze",  cmd_analyze))
    app.add_handler(CommandHandler("compare",  cmd_compare))
    app.add_handler(CommandHandler("movers",   cmd_movers))
    app.add_handler(CommandHandler("brief",    cmd_brief))
    app.add_handler(CommandHandler("alert",    cmd_alert))
    app.add_handler(CommandHandler("alerts",   cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))
    app.add_handler(CommandHandler("groups",   cmd_groups))
    app.add_handler(CommandHandler("add",      cmd_add))
    app.add_handler(CommandHandler("list",     cmd_list))
    app.add_handler(CommandHandler("earnings", cmd_earnings))

    # Scheduled jobs
    jq = app.job_queue
    jq.run_repeating(job_auto_scan,    interval=3600, first=120)   # cada hora en market hours
    jq.run_repeating(job_alert_checker, interval=60,  first=30)    # alertas cada 60 seg
    jq.run_daily(job_daily_open,  time=dtime(hour=9,  minute=35, tzinfo=ET))
    jq.run_daily(job_premarket_scan, time=dtime(hour=8, minute=30, tzinfo=ET))
    jq.run_daily(job_earnings_alert, time=dtime(hour=8, minute=0,  tzinfo=ET))

    app.post_init = lambda a: send_startup_message(a)

    log.info(f"✅ Bot running | Watchlist: {len(_watchlist)} stocks")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
