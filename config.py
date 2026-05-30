"""config.py — Stock Bot Settings"""
import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")

# Stocks to scan — Top picks across sectors
WATCHLIST = [
    # Semiconductors / Tech
    "NVDA", "AMD", "MU", "TSM", "AVGO", "QCOM", "INTC",
    # Big Tech
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA",
    # AI / Growth
    "PLTR", "SOUN", "AI", "SMCI", "ARM",
    # Healthcare / Pharma
    "NVO", "LLY", "ABBV", "MRNA",
    # Finance
    "JPM", "GS", "BAC", "V", "MA",
]

# ETF watchlist — sector benchmarks + broad market
ETF_WATCHLIST = [
    # Broad market
    "SPY", "QQQ", "IWM",
    # Sectors
    "SOXX", "SMH",   # Semiconductors
    "XLK",           # Technology
    "ARKK",          # AI / Disruptive Innovation
    "XLF",           # Financials
    "XLV",           # Healthcare
]

# Sector → ETF mapping (used for sector confirmation in scoring)
SECTOR_ETF_MAP = {
    # Individual stock sectors → which ETF confirms the move
    "NVDA": "SOXX", "AMD": "SOXX", "MU": "SOXX",
    "TSM": "SOXX",  "AVGO": "SOXX", "QCOM": "SOXX", "INTC": "SOXX",
    "AAPL": "QQQ",  "MSFT": "QQQ",  "GOOGL": "QQQ",
    "META": "QQQ",  "AMZN": "QQQ",  "TSLA": "QQQ",
    "PLTR": "ARKK", "SOUN": "ARKK", "AI": "ARKK",
    "SMCI": "SOXX", "ARM": "SOXX",
    "NVO":  "XLV",  "LLY": "XLV",   "ABBV": "XLV", "MRNA": "XLV",
    "JPM":  "XLF",  "GS":  "XLF",   "BAC": "XLF",
    "V":    "XLF",  "MA":  "XLF",
}

# Watchlist groups — use with /scan SECTOR or /groups
WATCHLIST_GROUPS = {
    "SEMIS":    ["NVDA", "AMD", "MU", "TSM", "AVGO", "QCOM", "INTC"],
    "BIGTECH":  ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA"],
    "AI":       ["NVDA", "PLTR", "SOUN", "AI", "SMCI", "ARM"],
    "HEALTH":   ["NVO", "LLY", "ABBV", "MRNA"],
    "FINANCE":  ["JPM", "GS", "BAC", "V", "MA"],
    "ETFS":     ["SPY", "QQQ", "IWM", "SOXX", "SMH", "XLK", "ARKK", "XLF", "XLV"],
}

# Minimum score to send alert
MIN_SCORE = 75

# Scan schedule (market hours ET)
SCAN_INTERVAL_MINUTES = 60   # Scan every hour during market hours
DAILY_REPORT_TIME     = "09:35"  # ET — right after market open
