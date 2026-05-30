"""
scanner.py — Stock Scanner using Yahoo Finance
═══════════════════════════════════════════════
Descarga datos OHLCV, calcula indicadores técnicos y
genera un score 0-100 para cada acción.

Indicadores:
  - EMA 9/21/50 — tendencia
  - RSI 14 — momentum / sobrecompra-sobreventa
  - MACD — señal de cruce
  - Volumen ratio — confirmación de movimiento
  - ATR 14 — volatilidad para SL/TP
  - 52-week position — contexto macro
"""

import yfinance as yf
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series):
    fast  = _ema(series, 12)
    slow  = _ema(series, 26)
    macd  = fast - slow
    signal = _ema(macd, 9)
    hist   = macd - signal
    return macd, signal, hist


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


# ─────────────────────────────────────────────────────────────
# Data fetch
# ─────────────────────────────────────────────────────────────

def fetch_stock_data(symbol: str, period: str = "6mo") -> dict | None:
    """
    Fetch OHLCV + fundamentals for a stock.
    Returns dict with price, indicators, fundamentals or None on error.
    """
    try:
        ticker = yf.Ticker(symbol)
        df     = ticker.history(period=period, interval="1d")

        if df.empty or len(df) < 60:
            return None

        close  = df["Close"]
        volume = df["Volume"]

        # Indicators
        ema9   = _ema(close, 9)
        ema21  = _ema(close, 21)
        ema50  = _ema(close, 50)
        rsi    = _rsi(close)
        _, _, macd_hist = _macd(close)
        atr    = _atr(df)
        vol_avg = volume.rolling(20).mean()
        vol_ratio = volume / vol_avg.replace(0, np.nan)

        # 52-week range
        high52 = close.rolling(252).max()
        low52  = close.rolling(252).min()
        range52 = (close - low52) / (high52 - low52 + 1e-9)

        # Latest values
        price     = round(close.iloc[-1], 2)
        atr_val   = round(atr.iloc[-1], 4)
        atr_pct   = round((atr_val / price) * 100, 2)

        # Fundamentals
        info   = ticker.info
        pe     = info.get("trailingPE") or info.get("forwardPE")
        mktcap = info.get("marketCap", 0)
        sector = info.get("sector", "Unknown")
        name   = info.get("shortName", symbol)

        return {
            "symbol":    symbol,
            "name":      name,
            "sector":    sector,
            "price":     price,
            "atr":       atr_val,
            "atr_pct":   atr_pct,
            "ema9":      round(ema9.iloc[-1], 4),
            "ema21":     round(ema21.iloc[-1], 4),
            "ema50":     round(ema50.iloc[-1], 4),
            "rsi":       round(rsi.iloc[-1], 2),
            "macd_hist": round(macd_hist.iloc[-1], 6),
            "macd_prev": round(macd_hist.iloc[-2], 6),
            "vol_ratio": round(vol_ratio.iloc[-1], 2),
            "range52":   round(range52.iloc[-1] * 100, 1),
            "pe":        round(pe, 1) if pe else None,
            "mktcap_b":  round(mktcap / 1e9, 1) if mktcap else None,
            "chg_1d":    round(((close.iloc[-1] / close.iloc[-2]) - 1) * 100, 2),
            "chg_5d":    round(((close.iloc[-1] / close.iloc[-6]) - 1) * 100, 2) if len(close) >= 6 else None,
        }

    except Exception as e:
        log.warning(f"fetch_stock_data({symbol}) error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────

def score_stock(data: dict) -> tuple[int, str, list[str]]:
    """
    Score a stock 0-100 and return (score, direction, reasons).
    direction: "LONG" | "SHORT" | "NEUTRAL"
    """
    score   = 50  # Base
    reasons = []
    bullish = 0
    bearish = 0

    price    = data["price"]
    ema9     = data["ema9"]
    ema21    = data["ema21"]
    ema50    = data["ema50"]
    rsi      = data["rsi"]
    macd_h   = data["macd_hist"]
    macd_p   = data["macd_prev"]
    vol_r    = data["vol_ratio"]
    range52  = data["range52"]
    chg_1d   = data["chg_1d"]

    # ── Trend (EMA alignment) ──────────────────────────────
    if price > ema9 > ema21 > ema50:
        bullish += 3
        reasons.append("📈 Precio > EMA9 > EMA21 > EMA50 (tendencia alcista perfecta)")
    elif price > ema21 > ema50:
        bullish += 2
        reasons.append("📈 Precio sobre EMA21/EMA50")
    elif price < ema9 < ema21 < ema50:
        bearish += 3
        reasons.append("📉 Precio < EMA9 < EMA21 < EMA50 (tendencia bajista)")
    elif price < ema21 < ema50:
        bearish += 2
        reasons.append("📉 Precio bajo EMA21/EMA50")

    # ── RSI ───────────────────────────────────────────────
    if 45 < rsi < 65:
        bullish += 2
        reasons.append(f"💪 RSI {rsi:.0f} — momentum alcista óptimo (sweet spot)")
    elif 65 <= rsi < 72:
        bullish += 1
        reasons.append(f"📊 RSI {rsi:.0f} — alcista pero vigilar extensión")
    elif rsi >= 72:
        bearish += 2
        reasons.append(f"🔴 RSI {rsi:.0f} — sobrecomprado / mal momento de entrada")
    elif 30 < rsi <= 45:
        bearish += 1
        reasons.append(f"📉 RSI {rsi:.0f} — momentum bajista")
    elif rsi <= 30:
        bullish += 1
        reasons.append(f"🔥 RSI {rsi:.0f} — sobreventa, posible rebote")

    # ── MACD ──────────────────────────────────────────────
    if macd_h > 0 and macd_h > macd_p:
        bullish += 2
        reasons.append("✅ MACD histograma positivo y expandiendo")
    elif macd_h > 0 and macd_h < macd_p:
        bullish += 1
        reasons.append("📊 MACD positivo pero contrayendo")
    elif macd_h < 0 and macd_h < macd_p:
        bearish += 2
        reasons.append("❌ MACD negativo y expandiendo (presión bajista)")
    elif macd_h < 0 and macd_h > macd_p:
        reasons.append("📊 MACD negativo pero mejorando")

    # ── Volume ────────────────────────────────────────────
    if vol_r >= 2.0:
        if bullish >= bearish:
            bullish += 2
            reasons.append(f"🔥 Volumen {vol_r:.1f}x promedio — fuerte interés comprador")
        else:
            bearish += 2
            reasons.append(f"🔥 Volumen {vol_r:.1f}x promedio — fuerte presión vendedora")
    elif vol_r >= 1.5:
        reasons.append(f"📊 Volumen {vol_r:.1f}x sobre promedio")
        bullish += 1 if bullish >= bearish else 0

    # ── 52-week position ──────────────────────────────────
    if range52 >= 80:
        bullish += 2
        reasons.append(f"🏆 Cerca de máximo 52 semanas ({range52:.0f}%)")
    elif range52 >= 60:
        bullish += 1
        reasons.append(f"💚 En zona alta del año ({range52:.0f}%)")
    elif range52 <= 20:
        bearish += 1
        reasons.append(f"⚠️ Cerca de mínimo 52 semanas ({range52:.0f}%)")

    # ── Daily change ──────────────────────────────────────
    if 1.0 <= chg_1d < 4.0:
        bullish += 1
        reasons.append(f"🚀 +{chg_1d:.1f}% hoy — momentum positivo")
    elif chg_1d >= 4.0:
        bearish += 1
        reasons.append(f"⚠️ +{chg_1d:.1f}% hoy — movimiento extendido, mal entry")
    elif chg_1d <= -3:
        bearish += 1
        reasons.append(f"💥 {chg_1d:.1f}% hoy — caída fuerte")

    # ── 5-day extension ───────────────────────────────────
    chg_5d = data.get("chg_5d") or 0
    if chg_5d >= 10:
        bearish += 1
        reasons.append(f"⚠️ +{chg_5d:.1f}% en 5 días — stock extendido, espera pullback")

    # ── Final score ───────────────────────────────────────
    net = bullish - bearish
    score = min(100, max(0, 50 + net * 7))

    if score >= 65:
        direction = "LONG"
    elif score <= 35:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    return score, direction, reasons


# ─────────────────────────────────────────────────────────────
# SL / TP calculator
# ─────────────────────────────────────────────────────────────

def calc_levels(data: dict, direction: str) -> dict:
    """Calculate entry, SL and TP levels based on ATR."""
    price   = data["price"]
    atr     = data["atr"]

    if direction == "LONG":
        sl  = round(price - atr * 1.5, 2)
        tp1 = round(price + atr * 2.0, 2)
        tp2 = round(price + atr * 3.5, 2)
    else:
        sl  = round(price + atr * 1.5, 2)
        tp1 = round(price - atr * 2.0, 2)
        tp2 = round(price - atr * 3.5, 2)

    rr = round(abs(tp1 - price) / abs(sl - price), 2)

    return {
        "entry": price,
        "sl":    sl,
        "tp1":   tp1,
        "tp2":   tp2,
        "rr":    rr,
    }


# ─────────────────────────────────────────────────────────────
# Parallel scanner
# ─────────────────────────────────────────────────────────────

def detect_breakout_setup(symbol: str) -> dict | None:
    """
    Detect price compression setups about to break out.
    Looks for: ATR shrinking + Bollinger squeeze + low volume + near key level.
    Returns setup dict or None if no compression detected.
    """
    try:
        ticker = yf.Ticker(symbol)
        df     = ticker.history(period="3mo", interval="1d")
        if df.empty or len(df) < 40:
            return None

        close  = df["Close"]
        volume = df["Volume"]
        price  = float(close.iloc[-1])

        # ATR compression: current ATR vs 20-day avg ATR
        atr_series = _atr(df)
        atr_now    = float(atr_series.iloc[-1])
        atr_avg    = float(atr_series.iloc[-20:].mean())
        atr_ratio  = atr_now / atr_avg if atr_avg else 1.0

        # Bollinger Band squeeze: current width vs 30-day avg width
        ema20  = _ema(close, 20)
        std20  = close.rolling(20).std()
        bb_width     = (4 * std20 / ema20)  # normalized width
        bb_width_now = float(bb_width.iloc[-1])
        bb_width_avg = float(bb_width.iloc[-30:].mean())
        bb_ratio     = bb_width_now / bb_width_avg if bb_width_avg else 1.0

        # Volume drying up (calm before storm)
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_now = float(volume.iloc[-1])
        vol_ratio = vol_now / vol_avg if vol_avg else 1.0

        # Price near EMA21 (coiling around key level)
        ema21     = float(_ema(close, 21).iloc[-1])
        near_ema  = abs(price - ema21) / ema21 < 0.02  # within 2%

        # Compression score
        score = 0
        reasons = []

        if atr_ratio < 0.75:
            score += 35
            reasons.append(f"🗜 ATR comprimido {atr_ratio:.0%} del promedio")
        elif atr_ratio < 0.90:
            score += 20
            reasons.append(f"⚡ ATR bajando ({atr_ratio:.0%})")

        if bb_ratio < 0.65:
            score += 35
            reasons.append(f"🔵 Bollinger squeeze ({bb_ratio:.0%})")
        elif bb_ratio < 0.80:
            score += 20
            reasons.append(f"📊 Bollinger contrayendo ({bb_ratio:.0%})")

        if vol_ratio < 0.7:
            score += 20
            reasons.append(f"😴 Volumen seco ({vol_ratio:.1f}x) — acumulación silenciosa")

        if near_ema:
            score += 10
            reasons.append(f"📍 Precio coiling en EMA21 (${ema21:.2f})")

        if score < 50:
            return None

        # Trend context
        ema50  = float(_ema(close, 50).iloc[-1])
        trend  = "ALCISTA" if price > ema50 else "BAJISTA"
        chg_1d = round(((close.iloc[-1] / close.iloc[-2]) - 1) * 100, 2)

        return {
            "symbol":     symbol,
            "price":      round(price, 2),
            "score":      score,
            "atr_ratio":  round(atr_ratio, 2),
            "bb_ratio":   round(bb_ratio, 2),
            "vol_ratio":  round(vol_ratio, 2),
            "trend":      trend,
            "chg_1d":     chg_1d,
            "reasons":    reasons,
        }

    except Exception as e:
        log.warning(f"breakout_detect({symbol}): {e}")
        return None


def scan_breakouts(symbols: list) -> list:
    """Scan for breakout compression setups across all symbols."""
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(detect_breakout_setup, s): s for s in symbols}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    results.append(res)
            except Exception:
                pass
    return sorted(results, key=lambda x: x["score"], reverse=True)


def scan_stocks(symbols: list, min_score: int = 65) -> list:
    """
    Scan multiple stocks in parallel.
    Returns list of opportunities sorted by score desc.
    """
    results = []

    def _analyze(sym):
        data = fetch_stock_data(sym)
        if not data:
            return None
        score, direction, reasons = score_stock(data)
        if direction == "NEUTRAL":
            return None

        # ── Hard quality filters ───────────────────────────
        # Require volume confirmation — no volume = no signal
        if data["vol_ratio"] < 1.2:
            log.debug(f"⛔ {sym} filtrado — volumen bajo ({data['vol_ratio']:.1f}x)")
            return None
        # Don't chase extended LONG signals
        if direction == "LONG" and data["rsi"] >= 75:
            log.debug(f"⛔ {sym} filtrado — RSI extendido ({data['rsi']:.0f})")
            return None
        # Don't short oversold stocks
        if direction == "SHORT" and data["rsi"] <= 25:
            log.debug(f"⛔ {sym} filtrado — RSI sobreventa ({data['rsi']:.0f})")
            return None

        # Earnings calendar filter — block if earnings too close
        earnings = {"blocked": False, "ok": False}
        try:
            from earnings_calendar import get_next_earnings
            earnings = get_next_earnings(sym)
            if earnings.get("blocked"):
                log.info(f"⛔ {sym} bloqueado — {earnings['reason']}")
                return None
        except Exception:
            pass

        levels = calc_levels(data, direction)
        return {
            **data,
            "score":     score,
            "direction": direction,
            "reasons":   reasons,
            "earnings":  earnings,
            **levels,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_analyze, s): s for s in symbols}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res and res["score"] >= min_score:
                    results.append(res)
            except Exception as e:
                log.warning(f"Scan error {futures[fut]}: {e}")

    return sorted(results, key=lambda x: x["score"], reverse=True)
