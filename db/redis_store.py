"""
redis_store.py — Redis Persistence Layer (StocksBot)
═════════════════════════════════════════════════════
Replaces in-memory dicts and JSON files that get wiped on deploy.

What's stored:
  - Price alerts       — survive restarts
  - Signal cooldown    — 24h per symbol (no repeat signals)
  - Watchlist          — persists across deploys

Railway injects REDIS_URL automatically.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

PREFIX    = "stocksbot"
_client   = None
_FALLBACK = {}


# ─────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────

def get_redis():
    global _client
    if _client is not None:
        return _client

    url = os.getenv("REDIS_URL") or os.getenv("REDIS_PRIVATE_URL")
    if not url:
        log.warning("⚠️  REDIS_URL not set — using in-memory fallback")
        return None

    try:
        import redis as redis_lib
        _client = redis_lib.from_url(url, decode_responses=True, socket_timeout=5)
        _client.ping()
        log.info("✅ Redis connected (StocksBot)")
        return _client
    except Exception as e:
        log.warning(f"⚠️  Redis failed: {e} — using in-memory fallback")
        return None


def is_available() -> bool:
    return get_redis() is not None


# ─────────────────────────────────────────────────────────────
# Signal Cooldown (replaces _last_alerted dict)
# ─────────────────────────────────────────────────────────────

def set_cooldown(symbol: str, hours: int = 24):
    """Mark symbol as recently alerted — blocks for `hours`."""
    key = f"{PREFIX}:cooldown:{symbol}"
    r   = get_redis()

    if r:
        try:
            r.set(key, str(datetime.now(timezone.utc).timestamp()), ex=int(hours * 3600))
            return
        except Exception as e:
            log.warning(f"Redis set_cooldown error: {e}")

    _FALLBACK[key] = datetime.now(timezone.utc).timestamp()


def check_cooldown(symbol: str, hours: int = 24) -> bool:
    """Returns True if symbol is in cooldown (should NOT be alerted)."""
    key = f"{PREFIX}:cooldown:{symbol}"
    r   = get_redis()

    if r:
        try:
            return r.exists(key) > 0
        except Exception as e:
            log.warning(f"Redis check_cooldown error: {e}")

    if key in _FALLBACK:
        elapsed = (datetime.now(timezone.utc).timestamp() - _FALLBACK[key]) / 3600
        if elapsed < hours:
            return True
        del _FALLBACK[key]
    return False


# ─────────────────────────────────────────────────────────────
# Price Alerts (replaces _alerts dict)
# ─────────────────────────────────────────────────────────────

def save_alert(symbol: str, alert_data: dict):
    """Save a price alert — survives restarts."""
    key = f"{PREFIX}:alert:{symbol}"
    r   = get_redis()

    if r:
        try:
            r.set(key, json.dumps(alert_data))
            return
        except Exception as e:
            log.warning(f"Redis save_alert error: {e}")

    _FALLBACK[key] = alert_data


def get_all_alerts() -> dict:
    """Load all active price alerts → {symbol: alert_data}."""
    r = get_redis()

    if r:
        try:
            keys   = r.keys(f"{PREFIX}:alert:*")
            alerts = {}
            for k in keys:
                sym  = k.replace(f"{PREFIX}:alert:", "")
                data = r.get(k)
                if data:
                    alerts[sym] = json.loads(data)
            return alerts
        except Exception as e:
            log.warning(f"Redis get_all_alerts error: {e}")

    return {k.replace(f"{PREFIX}:alert:", ""): v
            for k, v in _FALLBACK.items() if k.startswith(f"{PREFIX}:alert:")}


def delete_alert(symbol: str):
    """Remove a price alert."""
    key = f"{PREFIX}:alert:{symbol}"
    r   = get_redis()
    if r:
        try:
            r.delete(key)
            return
        except Exception as e:
            log.warning(f"Redis delete_alert error: {e}")
    _FALLBACK.pop(key, None)


# ─────────────────────────────────────────────────────────────
# Watchlist Persistence (replaces watchlist.json)
# ─────────────────────────────────────────────────────────────

WATCHLIST_KEY = f"{PREFIX}:watchlist"


def load_watchlist(fallback: list) -> list:
    """Load watchlist from Redis. Falls back to provided default."""
    r = get_redis()

    if r:
        try:
            data = r.get(WATCHLIST_KEY)
            if data:
                wl = json.loads(data)
                if isinstance(wl, list) and wl:
                    log.info(f"📋 Watchlist loaded from Redis: {len(wl)} stocks")
                    return wl
        except Exception as e:
            log.warning(f"Redis load_watchlist error: {e}")

    # Try local JSON file as secondary fallback
    from pathlib import Path
    wl_file = Path("watchlist.json")
    if wl_file.exists():
        try:
            wl = json.loads(wl_file.read_text())
            if isinstance(wl, list) and wl:
                return wl
        except Exception:
            pass

    return list(fallback)


def save_watchlist(watchlist: list):
    """Save watchlist to Redis (+ local file as backup)."""
    r = get_redis()

    if r:
        try:
            r.set(WATCHLIST_KEY, json.dumps(watchlist))
        except Exception as e:
            log.warning(f"Redis save_watchlist error: {e}")

    # Also save to local file as backup
    from pathlib import Path
    try:
        Path("watchlist.json").write_text(json.dumps(watchlist))
    except Exception:
        pass


def redis_status() -> str:
    """Return Redis connection status."""
    r = get_redis()
    if r:
        try:
            info = r.info("server")
            ver  = info.get("redis_version", "?")
            keys = r.dbsize()
            return f"🟢 Redis v{ver} — {keys} keys"
        except Exception:
            return "🟡 Redis conectado"
    return "🔴 Redis offline — usando memoria local"
