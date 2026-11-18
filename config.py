"""
config.py — central configuration for the BEP Support monitor.
"""

# Nifty index instrument key (spot LTP)
NIFTY_INDEX_KEY = "NSE_INDEX|Nifty 50"

# Underlying key used for option-chain / option-expiry lookups
NIFTY_OPTION_UNDERLYING_KEY = "NSE_INDEX|Nifty 50"

# Indices the BEP Support monitor can watch.
INDEXES = {
    "NIFTY":  {"index_key": "NSE_INDEX|Nifty 50", "underlying_key": "NSE_INDEX|Nifty 50",
               "strike_interval": 50,  "enabled": True},
    "SENSEX": {"index_key": "BSE_INDEX|SENSEX",   "underlying_key": "BSE_INDEX|SENSEX",
               "strike_interval": 100, "enabled": False},
}

STRIKE_INTERVAL = 50        
STRIKES_EACH_SIDE = 2       # nearest strike +/- 2 -> 5 strikes total

# Live scan interval (seconds).
SCAN_INTERVAL_SECONDS = 10
RECALC_INTERVAL_SECONDS = 60      

# Candle timing used by the BEP monitor
TRACK_FINALIZE_DELAY_SECONDS = 10   
TRACK_GIVE_UP_SECONDS = 180         

# Upstox
UPSTOX_ACCESS_TOKEN = ""   # paste a pre-generated access token

# Market hours (IST).
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:40"
MARKET_HOLIDAYS = []

# Alert pause switch. While True, BEP Support rows are still found and tabled, but NO toast or 
# browser notification is sent.
ALERTS_PAUSED = False

# BEP Support boards: True = check EVERY strike in the uploaded BEP CSV on every candle;
# False = only strikes inside that candle's ATM window.
SUPPORT_SCAN_ALL_CSV_STRIKES = True

# BEP Support failure window: 3 = 15 minutes.
SUPPORT_FAIL_WINDOW_CANDLES = 3

# ---------------------------------------------------------------- ALGO DELTA ORDERS
AUTO_ORDER_DRY_RUN = True         # "Dry run" checkbox. True = log the JSON only, send nothing.
AUTO_ORDER_PAUSED = False         # "Pause algo trade" button.
AUTO_ORDER_DAILY_LIMIT = 20       # "Max orders/day" box: hard cap on LIVE orders per day.

# Per-index AlgoDelta settings. 
# "tgt_type" and "sl_type" can be "POINT" or "LTP".
import copy as _copy

_STRATEGY_ORDER = {
    "type": "strategy_order",
    "exit_on_opposite": True,
    "is_tgt": True,
    "is_sl": True,
    "is_trail_set": False,
    "position_size": "{{strategy.position_size}}",
    "transaction_type": "BUY",
    "script_type": "{opt}",
    "is_rollover": False,
    "option_selection": "SYMBOL_BASED",
    "script": "{symbol}",
    "product": "INTRADAY",
    "quantity": "{qty}",
    "signal_type": "{signal}",
    "tgt_type": "{tgt_type}",
    "tgt_value": "{tgt}",
    "sl_type": "{sl_type}",
    "sl_value": "{sl}",
}

def _default_auto_order() -> dict:
    return {
        "webhook_url": "", "confirmed": False,
        "tgt": 50, "sl": 10, "tgt_type": "POINT", "sl_type": "POINT", "qty": 1,
        "templates": {"strategy_order": _copy.deepcopy(_STRATEGY_ORDER)},
    }

AUTO_ORDER = {name: _default_auto_order() for name in INDEXES}