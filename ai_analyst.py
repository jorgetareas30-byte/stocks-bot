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


def compare_stocks_with_claude(s1: dict, s2: dict) -> dict | None:
    """
    Ask Claude to compare two stocks head-to-head.
    Returns dict with winner, reasoning, and per-stock verdict.
    """
    client = _get_client()
    if not client:
        return None

    prompt = f"""Eres un analista de acciones experto. Compara estos dos stocks y dime cuál prefiero ahora mismo. Responde SOLO en JSON válido.

STOCK A: {s1['symbol']} ({s1['name']})
- Precio: ${s1['price']} | Score técnico: {s1['score']}/100 | Dirección: {s1['direction']}
- RSI: {s1['rsi']} | MACD hist: {s1['macd_hist']} | Vol ratio: {s1['vol_ratio']}x
- Cambio hoy: {s1['chg_1d']:+.1f}% | 52W pos: {s1['range52']}% | P/E: {s1.get('pe', 'N/A')}
- Sector: {s1['sector']} | Market cap: ${s1.get('mktcap_b', 'N/A')}B
- Señales: {', '.join(s1.get('reasons', [])[:3])}

STOCK B: {s2['symbol']} ({s2['name']})
- Precio: ${s2['price']} | Score técnico: {s2['score']}/100 | Dirección: {s2['direction']}
- RSI: {s2['rsi']} | MACD hist: {s2['macd_hist']} | Vol ratio: {s2['vol_ratio']}x
- Cambio hoy: {s2['chg_1d']:+.1f}% | 52W pos: {s2['range52']}% | P/E: {s2.get('pe', 'N/A')}
- Sector: {s2['sector']} | Market cap: ${s2.get('mktcap_b', 'N/A')}B
- Señales: {', '.join(s2.get('reasons', [])[:3])}

Responde SOLO con este JSON (sin texto extra):
{{
  "winner": "{s1['symbol']}" | "{s2['symbol']}" | "TIE",
  "confidence": <0-100>,
  "reason": "<1-2 oraciones: por qué uno gana al otro>",
  "stock_a": {{"verdict": "BUY"|"HOLD"|"AVOID", "note": "<1 oración>"}},
  "stock_b": {{"verdict": "BUY"|"HOLD"|"AVOID", "note": "<1 oración>"}},
  "timeframe": "<corto/medio/largo plazo>"
}}"""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-20250514",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        return json.loads(text)
    except Exception as e:
        log.warning(f"Claude compare error: {e}")
        return None


def format_compare_result(s1: dict, s2: dict, ai: dict | None) -> str:
    """Format /compare output for Telegram."""
    sym1, sym2 = s1['symbol'], s2['symbol']

    lines = [f"⚔️ <b>{sym1} vs {sym2}</b>\n"]

    # Score bar
    def score_bar(score):
        filled = round(score / 10)
        return "█" * filled + "░" * (10 - filled)

    lines.append(f"<b>{sym1}</b>  Score: {s1['score']}/100  {score_bar(s1['score'])}")
    lines.append(f"  💰 ${s1['price']} | RSI: {s1['rsi']:.0f} | {s1['chg_1d']:+.1f}% hoy | Vol: {s1['vol_ratio']}x")
    lines.append(f"  📊 {s1['direction']} | 52W: {s1['range52']:.0f}% | P/E: {s1.get('pe', 'N/A')}\n")

    lines.append(f"<b>{sym2}</b>  Score: {s2['score']}/100  {score_bar(s2['score'])}")
    lines.append(f"  💰 ${s2['price']} | RSI: {s2['rsi']:.0f} | {s2['chg_1d']:+.1f}% hoy | Vol: {s2['vol_ratio']}x")
    lines.append(f"  📊 {s2['direction']} | 52W: {s2['range52']:.0f}% | P/E: {s2.get('pe', 'N/A')}\n")

    if ai:
        winner = ai.get("winner", "TIE")
        conf   = ai.get("confidence", 0)
        if winner == "TIE":
            lines.append(f"🤖 <b>Claude AI: EMPATE</b> ({conf}% confianza)")
        else:
            trophy = "🏆"
            lines.append(f"🤖 <b>Claude AI: {trophy} {winner} gana</b> ({conf}% confianza)")

        lines.append(f"💡 {ai.get('reason', '')}")

        a_verdict = ai.get("stock_a", {})
        b_verdict = ai.get("stock_b", {})
        verdict_icons = {"BUY": "✅", "HOLD": "⏸", "AVOID": "❌"}
        lines.append(f"\n{verdict_icons.get(a_verdict.get('verdict',''), '•')} <b>{sym1}:</b> {a_verdict.get('note', '')}")
        lines.append(f"{verdict_icons.get(b_verdict.get('verdict',''), '•')} <b>{sym2}:</b> {b_verdict.get('note', '')}")
        lines.append(f"\n⏱ Horizonte: {ai.get('timeframe', 'corto plazo')}")
    else:
        # Fallback sin AI
        winner_sym = sym1 if s1['score'] >= s2['score'] else sym2
        lines.append(f"📊 Por score técnico: <b>{winner_sym}</b> ({max(s1['score'], s2['score'])}/100)")

    lines.append("\n⚠️ <i>No es consejo financiero.</i>")
    return "\n".join(lines)


def generate_morning_brief(market_data: dict) -> str | None:
    """
    Ask Claude to generate a personalized morning briefing in Spanish.
    market_data: {spy_price, spy_chg, vix, top_setups, pre_movers, earnings_today}
    """
    client = _get_client()
    if not client:
        return None

    setups_text = "\n".join([
        f"  - {s['symbol']} ({s['direction']}) Score:{s['score']}/100 RSI:{s['rsi']:.0f} +{s['chg_1d']:.1f}%"
        for s in market_data.get("top_setups", [])[:4]
    ]) or "  - Sin setups claros hoy"

    movers_text = "\n".join([
        f"  - {m['symbol']}: {m['chg_1d']:+.1f}%"
        for m in market_data.get("pre_movers", [])[:4]
    ]) or "  - Sin movers destacados"

    prompt = f"""Eres mi analista de bolsa personal. Son las 9:35 AM ET — el mercado acaba de abrir.

DATOS DEL MERCADO HOY:
- SPY: ${market_data.get('spy_price', 0):.2f} ({market_data.get('spy_chg', 0):+.2f}%)
- VIX: {market_data.get('vix', 0):.1f} {'(MIEDO ALTO ⚠️)' if market_data.get('vix', 0) > 25 else '(tranquilo)'}
- Movers pre-market:
{movers_text}
- Mejores setups técnicos de hoy:
{setups_text}
- Earnings hoy: {market_data.get('earnings_today', 'Ninguno relevante')}

Escríbeme un briefing de apertura en español, máximo 5 oraciones. Directo, sin rodeos, como si fuera un trader senior hablándome. Incluye: qué esperar del mercado hoy, el setup más interesante del día, y 1 riesgo a vigilar. No pongas disclaimers."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-20250514",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"Morning brief error: {e}")
        return None


def optimize_portfolio_with_claude(positions: list, market_data: dict) -> str | None:
    """
    Ask Claude to analyze current IBKR portfolio and give concrete recommendations.
    positions: [{symbol, shares, avg_cost, current_price, pnl_pct}, ...]
    """
    client = _get_client()
    if not client:
        return None

    pos_text = "\n".join([
        f"  - {p['symbol']}: {p['shares']} acc @ avg ${p['avg_cost']} → ahora ${p['current_price']} "
        f"({p['pnl_pct']:+.1f}%) P&L: ${p['pnl_usd']:+.2f}"
        for p in positions
    ])

    total_value  = sum(p['current_price'] * p['shares'] for p in positions)
    total_cost   = sum(p['avg_cost'] * p['shares'] for p in positions)
    total_pnl    = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0

    prompt = f"""Eres mi advisor de inversiones en acciones. Analiza mi portafolio de IBKR y dame recomendaciones concretas.

MI PORTAFOLIO ACTUAL:
{pos_text}

RESUMEN:
- Valor total: ${total_value:.2f}
- P&L total: ${total_pnl:+.2f} ({total_pnl_pct:+.1f}%)
- Cash disponible: ${market_data.get('cash', 0):.2f}

CONTEXTO DEL MERCADO:
- SPY hoy: {market_data.get('spy_chg', 0):+.2f}%
- VIX: {market_data.get('vix', 0):.1f}

Dame recomendaciones específicas en español:
1. ¿Qué posición está mejor y debería aumentar?
2. ¿Qué posición tiene más riesgo ahora mismo?
3. ¿Con el cash disponible, qué haría?
4. ¿Hay que proteger alguna posición con stop-loss?

Sé directo y concreto. Sin disclaimers genéricos."""

    try:
        resp = client.messages.create(
            model="claude-haiku-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"Portfolio optimizer error: {e}")
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
