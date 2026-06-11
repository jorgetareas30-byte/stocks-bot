"""
signal_history.py — Signal Outcome Tracking (StocksBot)
════════════════════════════════════════════════════════
Records every alerted signal and verifies outcomes against real
hourly highs/lows. Same philosophy as crypto-bot's signal_history:
if we don't measure win rate, the bot is just noise.

Storage: Redis list (stocksbot:signals) with in-memory fallback.

Outcomes:
  TP2      — second target hit (full win)
  TP1      — first target hit (partial win)
  SL       — stop loss hit (loss)
  EXPIRED  — 10 trading days without resolution
  OPEN     — still active
"""

import json
import logging
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

from db.redis_store import get_redis, PREFIX

log = logging.getLogger(__name__)

SIGNALS_KEY = f"{PREFIX}:signals"
EXPIRY_DAYS = 14          # calendar days ≈ 10 trading days
_FALLBACK: list = []


# ─────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────

def _load() -> list:
    r = get_redis()
    if r:
        try:
            raw = r.get(SIGNALS_KEY)
            return json.loads(raw) if raw else []
        except Exception as e:
            log.warning(f"signal_history load error: {e}")
    return list(_FALLBACK)


def _save(records: list):
    global _FALLBACK
    r = get_redis()
    if r:
        try:
            r.set(SIGNALS_KEY, json.dumps(records))
            return
        except Exception as e:
            log.warning(f"signal_history save error: {e}")
    _FALLBACK = list(records)


# ─────────────────────────────────────────────────────────────
# Recording
# ─────────────────────────────────────────────────────────────

def record_signal(stock: dict, source: str = "auto_scan"):
    """Record an alerted signal. Call right after sending the alert."""
    try:
        records = _load()
        records.append({
            "id":        len(records) + 1,
            "ts":        datetime.now(timezone.utc).isoformat(),
            "symbol":    stock["symbol"],
            "direction": stock["direction"],
            "score":     stock["score"],
            "entry":     stock["entry"],
            "sl":        stock["sl"],
            "tp1":       stock["tp1"],
            "tp2":       stock["tp2"],
            "source":    source,
            "outcome":   "OPEN",
            "pnl_pct":   None,
            "closed_ts": None,
        })
        _save(records)
        log.info(f"📝 Signal recorded: {stock['symbol']} {stock['direction']} @ {stock['entry']}")
    except Exception as e:
        log.warning(f"record_signal error: {e}")


# ─────────────────────────────────────────────────────────────
# Outcome verification
# ─────────────────────────────────────────────────────────────

def _check_one(rec: dict) -> dict | None:
    """Walk hourly bars since signal time; return updated record or None."""
    sig_time = datetime.fromisoformat(rec["ts"])
    days = (datetime.now(timezone.utc) - sig_time).days + 2

    df = yf.Ticker(rec["symbol"]).history(period=f"{min(days, 60)}d", interval="1h")
    if df.empty:
        return None
    cutoff = pd.Timestamp(sig_time)
    if df.index.tz is not None:
        cutoff = cutoff.tz_convert(df.index.tz)
    else:
        cutoff = cutoff.tz_localize(None)
    df = df[df.index > cutoff]
    if df.empty:
        return None

    entry, sl, tp1, tp2 = rec["entry"], rec["sl"], rec["tp1"], rec["tp2"]
    is_long = rec["direction"] == "LONG"
    tp1_hit = False

    for ts, bar in df.iterrows():
        hi, lo = float(bar["High"]), float(bar["Low"])

        if not tp1_hit:
            sl_hit  = lo <= sl if is_long else hi >= sl
            tp1_now = hi >= tp1 if is_long else lo <= tp1
            if sl_hit:
                pnl = -abs(entry - sl) / entry * 100
                return {**rec, "outcome": "SL", "pnl_pct": round(pnl, 2),
                        "closed_ts": str(ts)}
            if tp1_now:
                tp1_hit = True
        else:
            # After TP1: SL moves to breakeven, hunt TP2
            be_hit  = lo <= entry if is_long else hi >= entry
            tp2_now = hi >= tp2 if is_long else lo <= tp2
            if tp2_now:
                pnl = (abs(tp1 - entry) + abs(tp2 - entry)) / entry / 2 * 100
                return {**rec, "outcome": "TP2", "pnl_pct": round(pnl, 2),
                        "closed_ts": str(ts)}
            if be_hit:
                pnl = abs(tp1 - entry) / entry / 2 * 100
                return {**rec, "outcome": "TP1", "pnl_pct": round(pnl, 2),
                        "closed_ts": str(ts)}

    # Unresolved — expire if too old
    if (datetime.now(timezone.utc) - sig_time).days >= EXPIRY_DAYS:
        last_close = float(df["Close"].iloc[-1])
        raw = (last_close - entry) / entry * 100
        pnl = raw if is_long else -raw
        if tp1_hit:
            pnl = abs(tp1 - entry) / entry / 2 * 100 + pnl / 2
        return {**rec, "outcome": "EXPIRED", "pnl_pct": round(pnl, 2),
                "closed_ts": datetime.now(timezone.utc).isoformat()}
    return None


def update_outcomes() -> int:
    """Check all OPEN signals. Returns number of newly closed signals."""
    records = _load()
    closed = 0
    for i, rec in enumerate(records):
        if rec["outcome"] != "OPEN":
            continue
        try:
            updated = _check_one(rec)
            if updated:
                records[i] = updated
                closed += 1
                log.info(f"Signal {rec['symbol']} → {updated['outcome']} ({updated['pnl_pct']}%)")
        except Exception as e:
            log.warning(f"update_outcomes {rec['symbol']}: {e}")
    if closed:
        _save(records)
    return closed


# ─────────────────────────────────────────────────────────────
# Stats & reporting
# ─────────────────────────────────────────────────────────────

def get_stats() -> dict:
    records = [r for r in _load() if r["outcome"] not in ("OPEN",)]
    total = len(records)
    if not total:
        return {"total": 0}

    wins   = [r for r in records if (r["pnl_pct"] or 0) > 0]
    losses = [r for r in records if (r["pnl_pct"] or 0) < 0]
    pnls   = [r["pnl_pct"] or 0 for r in records]
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))

    return {
        "total":         total,
        "open":          len([r for r in _load() if r["outcome"] == "OPEN"]),
        "win_rate":      round(len(wins) / total * 100, 1),
        "expectancy":    round(sum(pnls) / total, 3),
        "profit_factor": round(gp / gl, 2) if gl else float("inf"),
        "avg_win":       round(gp / len(wins), 2) if wins else 0,
        "avg_loss":      round(-gl / len(losses), 2) if losses else 0,
        "outcomes":      {o: len([r for r in records if r["outcome"] == o])
                          for o in ("TP2", "TP1", "SL", "EXPIRED")},
    }


def format_performance() -> str:
    """HTML report for Telegram — /performance and weekly job."""
    stats = get_stats()
    if stats["total"] == 0:
        open_n = len([r for r in _load() if r["outcome"] == "OPEN"])
        return (f"📊 <b>PERFORMANCE</b>\n\nSin señales cerradas todavía.\n"
                f"⏳ Abiertas: {open_n}")

    wr   = stats["win_rate"]
    icon = "🔥" if wr >= 60 else "✅" if wr >= 50 else "⚠️"
    o    = stats["outcomes"]
    return "\n".join([
        "📊 <b>PERFORMANCE — SEÑALES VERIFICADAS</b>\n",
        f"🎯 Win rate: <b>{wr}%</b> {icon} ({stats['total']} cerradas, {stats['open']} abiertas)",
        f"💰 Expectancy: <b>{stats['expectancy']:+.3f}%</b> por señal",
        f"📈 Profit factor: <b>{stats['profit_factor']}</b>",
        f"   Avg win {stats['avg_win']:+.2f}% | Avg loss {stats['avg_loss']:+.2f}%",
        "",
        f"🏆 TP2: {o['TP2']}  ✅ TP1: {o['TP1']}  ❌ SL: {o['SL']}  ⌛ Exp: {o['EXPIRED']}",
        "",
        "<i>Verificado contra highs/lows horarios reales.</i>",
    ])
