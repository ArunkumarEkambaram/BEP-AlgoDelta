"""
trade_tracker.py - Entry / Exit / LTP / Captured Points / P&L for the AlgoDelta orders table.

SENT rows:    entry and exit are the real fills from today's Upstox trade book
              (GET /v2/order/trades/get-trades-for-day), matched by the option's instrument key.
              BUY fills = entry (quantity-weighted average), SELL fills = exit. Once the sold
              quantity covers the bought quantity the trade is closed and Captured Points = Exit - Entry;
              while it is open, Captured Points = live LTP - Entry. P&L = points x filled quantity (units).
DRY RUN rows: nothing was placed, so entry = the option LTP when the signal fired and Captured Points
              = live LTP - entry. P&L = points x quantity (lots) x lot size.
FAILED / BLOCKED rows: never entered a trade; all these columns stay "--".
"""
import config
import market_utils

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


def compute(client, rows, expiry_by_index, trades=None):
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
            entry, exit_, qty_units = _f(r.get("ltp")), None, None
            lots = _f(r.get("qty")) or _f(config.AUTO_ORDER.get(r.get("index"), {}).get("qty")) or 1
            qty_units = lots * config.INDEXES.get(r.get("index"), {}).get("lot_size", 1)
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


def _keep(row, key):
    return row.get(key, "")


def _points(entry, exit_, ltp, qty_units):
    if entry is None:
        return {"entry": "--", "exit": "--", "points": "--", "pnl": "--"}
    ref = exit_ if exit_ is not None else ltp
    pts = round(ref - entry, 2) if ref is not None else None
    pnl = round(pts * qty_units, 2) if pts is not None and qty_units else None
    return {"entry": round(entry, 2), "exit": round(exit_, 2) if exit_ is not None else "--",
            "points": pts if pts is not None else "--", "pnl": pnl if pnl is not None else "--"}
