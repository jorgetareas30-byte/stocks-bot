"""
earnings_calendar.py — Earnings Date Filter
════════════════════════════════════════════
Bloquea señales de acciones 3 días antes y 1 día después
de su fecha de earnings. Los reportes crean volatilidad
impredecible — ningún análisis técnico puede predecirlos.

Fuente: yfinance (gratis, sin API key).
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import yfinance as yf

log = logging.getLogger(__name__)

BLOCK_DAYS_BEFORE = 3    # bloquear N días antes del earnings
BLOCK_DAYS_AFTER  = 1    # bloquear N días después del earnings


# ── Core fetch ────────────────────────────────────────────────

def get_next_earnings(ticker: str) -> dict:
    """
    Retorna info del próximo earnings para el ticker.
    {date, days_away, blocked, reason, ok}
    """
    try:
        t       = yf.Ticker(ticker)
        cal     = t.calendar  # DataFrame con earnings info

        if cal is None or cal.empty:
            return _no_earnings(ticker)

        # Puede ser un DataFrame con columna 'Earnings Date'
        # o un dict con key 'Earnings Date'
        if hasattr(cal, "columns"):
            # Es un DataFrame
            if "Earnings Date" in cal.columns:
                dates = cal["Earnings Date"].dropna()
                if dates.empty:
                    return _no_earnings(ticker)
                earnings_date = dates.iloc[0]
            else:
                return _no_earnings(ticker)
        elif isinstance(cal, dict):
            earnings_date = cal.get("Earnings Date", [None])
            if isinstance(earnings_date, list):
                earnings_date = earnings_date[0] if earnings_date else None
            if earnings_date is None:
                return _no_earnings(ticker)
        else:
            return _no_earnings(ticker)

        # Normalizar a datetime aware
        if hasattr(earnings_date, "to_pydatetime"):
            earnings_date = earnings_date.to_pydatetime()
        if not hasattr(earnings_date, "tzinfo") or earnings_date.tzinfo is None:
            earnings_date = earnings_date.replace(tzinfo=timezone.utc)

        now      = datetime.now(timezone.utc)
        days_away = (earnings_date - now).days

        blocked = (
            -BLOCK_DAYS_AFTER <= days_away <= BLOCK_DAYS_BEFORE
        )

        reason = None
        if blocked:
            if days_away < 0:
                reason = (
                    f"⚠️ Earnings fue hace {abs(days_away)}d — "
                    f"volatilidad post-earnings, señal bloqueada"
                )
            elif days_away == 0:
                reason = f"⚠️ ¡Earnings HOY! Señal bloqueada"
            else:
                reason = (
                    f"⚠️ Earnings en {days_away}d "
                    f"({earnings_date.strftime('%b %d')}) — señal bloqueada"
                )

        return {
            "ticker":     ticker,
            "date":       earnings_date.strftime("%Y-%m-%d"),
            "days_away":  days_away,
            "blocked":    blocked,
            "reason":     reason,
            "ok":         True,
        }

    except Exception as e:
        log.debug(f"Earnings fetch error ({ticker}): {e}")
        return _no_earnings(ticker)


def _no_earnings(ticker: str) -> dict:
    return {
        "ticker":    ticker,
        "date":      None,
        "days_away": 999,
        "blocked":   False,
        "reason":    None,
        "ok":        False,
    }


# ── Batch fetch ───────────────────────────────────────────────

def get_earnings_batch(tickers: list) -> dict:
    """
    Fetch earnings dates for multiple tickers.
    Returns {ticker: earnings_info}
    """
    results = {}
    for ticker in tickers:
        results[ticker] = get_next_earnings(ticker)
    return results


# ── Formatting ────────────────────────────────────────────────

def format_earnings_line(info: dict) -> str:
    """Short line for stock alert."""
    if not info.get("ok") or not info.get("date"):
        return ""
    days   = info["days_away"]
    date   = info["date"]
    if days <= 0:
        return f"📅 Earnings: hace {abs(days)}d ({date}) ⚠️"
    elif days <= 7:
        return f"📅 Earnings: en {days}d ({date}) ⚠️"
    else:
        return f"📅 Earnings: {date} ({days}d)"


def format_earnings_calendar(earnings_map: dict) -> str:
    """Full earnings calendar for /earnings command."""
    if not earnings_map:
        return "📭 Sin datos de earnings."

    upcoming = [
        (t, e) for t, e in earnings_map.items()
        if e.get("ok") and e.get("date") and 0 <= e.get("days_away", 999) <= 30
    ]
    upcoming.sort(key=lambda x: x[1]["days_away"])

    if not upcoming:
        return "📅 No hay earnings en los próximos 30 días para el watchlist."

    lines = ["📅 <b>Próximos Earnings (30 días)</b>\n"]
    for ticker, info in upcoming:
        days = info["days_away"]
        warn = " ⚠️" if days <= 3 else ""
        lines.append(
            f"{'🔴' if days <= 3 else '🟡' if days <= 7 else '🟢'} "
            f"<b>{ticker}</b> — {info['date']} (en {days}d){warn}"
        )

    lines.append(
        "\n⚠️ = bloqueado (±3 días). "
        "Señales bloqueadas automáticamente."
    )
    return "\n".join(lines)
