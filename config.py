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
    # ETFs
    "SPY", "QQQ", "SOXX",
]

# Minimum score to send alert
MIN_SCORE = 65

# Scan schedule (market hours ET)
SCAN_INTERVAL_MINUTES = 60   # Scan every hour during market hours
DAILY_REPORT_TIME     = "09:35"  # ET — right after market open
