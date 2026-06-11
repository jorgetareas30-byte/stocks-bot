"""
postgres_positions.py — Posiciones IBKR desde Postgres (fuente única de verdad)
═══════════════════════════════════════════════════════════════════════════════
Lee fin_stock_positions, la misma tabla que usa el Financial Advisor.
Se actualiza UNA vez (en Postgres) y todos los bots ven lo mismo.
Fallback a None si no hay DATABASE_URL — el caller decide qué hacer.
"""

import os
import logging

log = logging.getLogger(__name__)


def get_ibkr_positions() -> list[dict] | None:
    """[{symbol, shares, avg_cost}] desde Postgres, o None si no disponible."""
    url = os.getenv("DATABASE_URL")
    if not url:
        log.warning("DATABASE_URL no configurada — /portfolio usará fallback")
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(url, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT ticker, shares, avg_price_usd FROM fin_stock_positions ORDER BY ticker")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return None
        return [{"symbol": r[0], "shares": float(r[1]), "avg_cost": float(r[2])} for r in rows]
    except Exception as e:
        log.warning(f"Postgres positions error: {e}")
        return None
