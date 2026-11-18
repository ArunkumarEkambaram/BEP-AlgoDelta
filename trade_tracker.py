"""
trade_tracker.py - Entry / Exit / LTP / Captured Points / P&L for the AlgoDelta orders table.

SENT rows:    entry and exit are the real fills from today's Upstox trade book
              (GET /v2/order/trades/get-trades-for-day), matched by the option's instrument key.
              BUY fills = entry (quantity-weighted average), SELL fills = exit. Once the sold
              quantity covers the bought quantity the trade is closed and Captured Points = Exit - Entry,
              P&L = points x filled quantity (units). While it is open, Points and P&L show "--".
DRY RUN rows: nothing was placed, so entry = the option LTP when the signal fired and the exit is SIMULATED
              from Upstox 1-minute candles after the entry minute, using the Target / SL / trailing SL that were
              in the order's JSON (see simulate_exit). P&L = points x lots x lot size. Once found, the exit
              is saved in today's orders file. LTP (live) is shown for every tracked row.
FAILED / BLOCKED rows: never entered a trade; all these columns stay "--".
"""
import json
from datetime import datetime, time as dtime, timedelta

import config
import market_utils

DRY_EXIT_TIME = dtime(15, 15)            # open dry-run trades are closed at the 15:15 candle's open

TRACKED = ("SENT", "DRY RUN")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _avg(fills):
    qty = sum(q for q, _p in fills)
    return (sum(q * p for q, p in fills) / qty, qty) if qty else (None, 0)


def _instrument_key(client, row, expiry_by_index):
    """Instrument key of the row's option. Stored on the row once found."""
    if row.get("ik"):
        return row["ik"]
    idx = row.get("index")
    expiry = row.get("expiry") or expiry_by_index.get(idx)
    if not idx or idx not in config.INDEXES or not expiry:
        return None
    mapping, _ = market_utils.option_instrument_keys(client, expiry, config.INDEXES[idx]["underlying_key"])
    try:
        ik = (mapping or {}).get(int(float(row["strike"])), {}).get(row["opt"])
    except (KeyError, TypeError, ValueError):
        ik = None
    if ik:
        row["ik"] = ik
    return ik


def compute(client, rows, expiry_by_index, trades=None, now=None):
    """
    Works out the live columns for every tracked row. Returns ({row_id: fields}, error_or_None).
    `trades` is today's Upstox trade list (None = not fetched this time; SENT rows then keep their fills).
    Runs on a worker thread: it only reads `rows` (plus caching "ik") and returns the new values.
    """
    tracked = [r for r in rows if r.get("status") in TRACKED]
    if not tracked:
        return {}, None

    iks = {}
    for r in tracked:
        ik = _instrument_key(client, r, expiry_by_index)
        if ik:
            iks[r["id"]] = ik

    ltp_map, err = client.fetch_ltp(sorted(set(iks.values()))) if iks else ({}, None)
    ltp_map = ltp_map or {}

    fills = {}
    if trades is not None:
        for t in trades:
            ik = t.get("instrument_token") or t.get("instrument_key")
            side = (t.get("transaction_type") or "").upper()
            qty, price = _f(t.get("quantity")), _f(t.get("average_price"))
            if ik and side in ("BUY", "SELL") and qty and price is not None:
                fills.setdefault(ik, {"BUY": [], "SELL": []})[side].append((qty, price))

    out = {}
    for r in tracked:
        ik = iks.get(r["id"])
        ltp = ltp_map.get(ik) if ik else None
        if ltp is None and ik:                        # key may come back as NSE_FO:xxx instead of NSE_FO|xxx
            ltp = ltp_map.get(ik.replace("|", ":"))
        fields = {"ltp_live": round(ltp, 2) if ltp is not None else _keep(r, "ltp_live")}

        if r["status"] == "DRY RUN":
            entry = _f(r.get("ltp"))
            lots = _f(r.get("qty")) or _f(config.AUTO_ORDER.get(r.get("index"), {}).get("qty")) or 1
            qty_units = lots * config.INDEXES.get(r.get("index"), {}).get("lot_size", 1)
            exit_ = _f(r.get("exit"))
            if exit_ is None and entry is not None and ik:
                candles, _cerr = client.fetch_intraday_candles(ik, 1)
                res = simulate_exit(entry, r.get("time", ""), candles or [], _params(r), now or
                                    datetime.now(market_utils.IST))
                if res:
                    exit_, exit_time, reason = res
                    fields.update(exit_time=exit_time, exit_reason=reason, exit_new=True)
        else:                                         # SENT: real fills from Upstox
            if trades is None:
                out[r["id"]] = {**fields, **_points(_f(r.get("entry")), _f(r.get("exit")), ltp,
                                                    _f(r.get("filled_qty")))}
                continue
            f = fills.get(ik, {"BUY": [], "SELL": []}) if ik else {"BUY": [], "SELL": []}
            entry, bought = _avg(f["BUY"])
            sold_avg, sold = _avg(f["SELL"])
            exit_ = sold_avg if bought and sold >= bought else None
            qty_units = bought or None
            fields["filled_qty"] = int(bought) if bought else ""
        fields.update(_points(entry, exit_, ltp, qty_units))
        out[r["id"]] = fields
    return out, err


def _params(row) -> dict:
    """Target / SL / trail settings that were sent with this order (its saved JSON); current settings as fallback."""
    try:
        p = json.loads(row.get("payload") or "{}")
    except ValueError:
        p = {}
    cfg = config.AUTO_ORDER.get(row.get("index"), {})
    return {
        "tgt_type": p.get("tgt_type", cfg.get("tgt_type", "POINT")), "tgt": _f(p.get("tgt_value", cfg.get("tgt"))),
        "sl_type": p.get("sl_type", cfg.get("sl_type", "POINT")), "sl": _f(p.get("sl_value", cfg.get("sl"))),
        "trail": bool(p.get("is_trail_set", cfg.get("trail", False))),
        "trigger": _f(p.get("trail_trigger", cfg.get("trail_trigger"))),
        "gap": _f(p.get("trail_gap", cfg.get("trail_gap"))), "step": _f(p.get("trail_point", cfg.get("trail_point"))) or 1,
    }


def simulate_exit(entry: float, entry_time: str, candles: list, prm: dict, now):
    """
    Dry-run exit from 1-minute candles that start AFTER the entry minute (the forming one included).
      Target: POINT = entry + value, LTP = that price.  SL: POINT = entry - value, LTP = that price.
      Trailing SL (if on): once the highest price reaches entry + trigger, SL = highest - gap (moved in steps
      of `step` points) and never moves down. E.g. entry 178, SL 166, trigger 20, gap 20: at 198 SL = 178 (cost),
      at 210 SL = 190.
      Per candle: SL is checked first (if SL and target are hit in the same minute, it counts as SL), then
      target; the trail is raised from that candle's high for the NEXT candle.
      End of day: still open at 15:15 -> exit at the 15:15 candle's open.
    Returns (exit_price, "HH:MM", reason) or None while the trade is still open.
    """
    try:
        hh, mm, *_ = (int(x) for x in entry_time.split(":"))
    except ValueError:
        return None
    day = now.astimezone(market_utils.IST) if now.tzinfo else now
    entry_min = market_utils.IST.localize(datetime(day.year, day.month, day.day, hh, mm)) if day.tzinfo is None \
        else day.replace(hour=hh, minute=mm, second=0, microsecond=0)
    target = entry + prm["tgt"] if prm["tgt_type"] == "POINT" else prm["tgt"]
    sl = entry - prm["sl"] if prm["sl_type"] == "POINT" else prm["sl"]
    if target is None or sl is None:
        return None
    trailed, high = False, entry
    for c in sorted(candles, key=lambda c: c[0]):
        start = datetime.fromisoformat(c[0])
        start = start.astimezone(market_utils.IST) if start.tzinfo else market_utils.IST.localize(start)
        if start.date() != entry_min.date() or start <= entry_min:
            continue
        o, h, l = float(c[1]), float(c[2]), float(c[3])
        label = start.strftime("%H:%M")
        if start.time() >= DRY_EXIT_TIME:
            return round(o, 2), label, "End of day 15:15"
        if l <= sl:
            return round(sl, 2), label, ("Trailing SL" if trailed else "SL")
        if h >= target:
            return round(target, 2), label, "Target"
        high = max(high, h)
        if prm["trail"] and prm["trigger"] is not None and prm["gap"] is not None and high >= entry + prm["trigger"]:
            steps = int((high - prm["gap"] - entry) // prm["step"])
            new_sl = entry + steps * prm["step"]
            if new_sl > sl:
                sl, trailed = new_sl, True
    if now.astimezone(market_utils.IST).time() >= DRY_EXIT_TIME and now.date() == entry_min.date() and candles:
        last = sorted(candles, key=lambda c: c[0])[-1]
        return round(float(last[4]), 2), now.strftime("%H:%M"), "End of day 15:15"
    return None


def _keep(row, key):
    return row.get(key, "")


def _points(entry, exit_, ltp, qty_units):
    if entry is None:
        return {"entry": "--", "exit": "--", "points": "--", "pnl": "--"}
    pts = round(exit_ - entry, 2) if exit_ is not None else None      # Captured Points only once exited
    pnl = round(pts * qty_units, 2) if pts is not None and qty_units else None
    return {"entry": round(entry, 2), "exit": round(exit_, 2) if exit_ is not None else "--",
            "points": pts if pts is not None else "--", "pnl": pnl if pnl is not None else "--"}
