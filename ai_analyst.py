"""
ai_analyst.py — Claude AI Stock Analyst
════════════════════════════════════════
Claude analiza cada oportunidad de stock con contexto
técnico + fundamental y genera un veredicto detallado.
"""

import os
import json
import logging
import anthropic

log = logging.getLogger(__name__)

_client = None

def _get_client():
    global _client
    if _client is None:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            return None
        _client = anthropic.Anthropic(api_key=key)
    return _client


def analyze_stock_with_claude(stock: dict) -> dict | None:
    """
    Send stock data to Claude and get AI analysis.
    Returns dict with verdict, confidence, catalysts, risks, target.
    """
    client = _get_client()
    if not client:
        return None

    prompt = f"""Eres un analista de acciones experto. Analiza esta oportunidad y responde SOLO en JSON válido.

DATOS DEL STOCK:
- Símbolo: {stock['symbol']} ({stock['name']})
- Sector: {stock['sector']}
- Precio actual: ${stock['price']}
- Dirección técnica: {stock['direction']}
- Score técnico: {stock['score']}/100
- RSI: {stock['rsi']}
- Cambio hoy: {stock['chg_1d']:+.1f}%
- Cambio 5 días: {stock.get('chg_5d', 'N/A')}%
- Posición en rango 52 semanas: {stock['range52']}%
- Ratio de volumen: {stock['vol_ratio']}x promedio
- P/E ratio: {stock['pe'] or 'N/A'}
- Market cap: ${stock['mktcap_b'] or 'N/A'}B
- Señales técnicas: {', '.join(stock['reasons'][:4])}

Responde SOLO con este JSON (sin texto extra):
{{
  "verdict": "STRONG_BUY" | "BUY" | "WEAK_BUY" | "HOLD" | "AVOID",
  "confidence": <0-100>,
  "thesis": "<1 oración máximo: por qué es buena/mala oportunidad>",
  "catalysts": ["<catalizador 1>", "<catalizador 2>"],
  "risks": ["<riesgo principal>"],
  "price_target_30d": <precio objetivo a 30 días>,
  "best_entry": "<estrategia de entrada: market/limit/wait>",
  "position_size": "<small/medium/large — según risk/reward>"
}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        # Extract JSON if wrapped in code block
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        return json.loads(text)
    except Exception as e:
        log.warning(f"Claude analysis error ({stock['symbol']}): {e}")
        return None


def format_stock_alert(stock: dict, ai: dict | None) -> str:
    """Format a complete Telegram alert for a stock opportunity."""
    arrow = "🟢" if stock["direction"] == "LONG" else "🔴"
    score = stock["score"]

    if score >= 80:
        score_icon = "🔥"
    elif score >= 70:
        score_icon = "✅"
    else:
        score_icon = "⚡"

    lines = [
        f"{arrow} <b>{stock['symbol']}</b> — {stock['name']}",
        f"📊 Score: <b>{score}/100</b> {score_icon} | {stock['direction']}",
        f"💰 Precio: <b>${stock['price']}</b> | Vol: {stock['vol_ratio']}x",
        f"📈 Hoy: {stock['chg_1d']:+.1f}% | RSI: {stock['rsi']:.0f} | 52W: {stock['range52']:.0f}%",
        "",
        f"🎯 Entry: <b>${stock['entry']}</b>",
        f"🛡 SL: ${stock['sl']} | TP1: ${stock['tp1']} | TP2: ${stock['tp2']}",
        f"⚖️ R/R: {stock['rr']}:1",
    ]

    # Technical reasons (top 3)
    if stock.get("reasons"):
        lines.append("")
        lines.append("📋 <b>Señales técnicas:</b>")
        for r in stock["reasons"][:3]:
            lines.append(f"  {r}")

    # AI analysis
    if ai:
        verdict_map = {
            "STRONG_BUY": "🔥 COMPRA FUERTE",
            "BUY":        "✅ COMPRAR",
            "WEAK_BUY":   "⚡ COMPRA DÉBIL",
            "HOLD":       "⏸ MANTENER",
            "AVOID":      "❌ EVITAR",
        }
        verdict_label = verdict_map.get(ai.get("verdict", ""), ai.get("verdict", ""))

        lines.append("")
        lines.append(f"🤖 <b>Claude AI:</b> {verdict_label} ({ai.get('confidence', 0)}% confianza)")
        if ai.get("thesis"):
            lines.append(f"💡 {ai['thesis']}")
        if ai.get("catalysts"):
            lines.append(f"🚀 Catalizadores: {', '.join(ai['catalysts'][:2])}")
        if ai.get("risks"):
            lines.append(f"⚠️ Riesgo: {ai['risks'][0]}")
        if ai.get("price_target_30d"):
            upside = round(((ai["price_target_30d"] / stock["price"]) - 1) * 100, 1)
            lines.append(f"🎯 Target 30d: ${ai['price_target_30d']} ({upside:+.1f}%)")

    # Earnings info
    earnings = stock.get("earnings", {})
    if earnings.get("ok") and earnings.get("date"):
        try:
            from earnings_calendar import format_earnings_line
            earn_line = format_earnings_line(earnings)
            if earn_line:
                lines.append(earn_line)
        except Exception:
            pass

    lines.append("")
    lines.append(f"📊 Sector: {stock['sector']} | Cap: ${stock.get('mktcap_b', 'N/A')}B | P/E: {stock.get('pe', 'N/A')}")
    lines.append("⚠️ <i>No es consejo financiero. Gestiona tu riesgo.</i>")

    return "\n".join(lines)
