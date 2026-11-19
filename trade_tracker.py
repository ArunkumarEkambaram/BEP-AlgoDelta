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
import exit_rules
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
                res = exit_rules.evaluate(entry, r.get("time", ""), candles or [],
                                          base_rules(_params(r)) + custom_rules(r),
                                          now or datetime.now(market_utils.IST), eod=True)
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
            rules = custom_rules(r)
            if rules and exit_ is None and entry is not None and not r.get("c_done") and ik:
                candles, _cerr = client.fetch_intraday_candles(ik, 1)
                hit = exit_rules.evaluate(entry, r.get("time", ""), candles or [], rules,
                                          now or datetime.now(market_utils.IST), eod=False)
                if hit:
                    fields["custom_hit"] = hit
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
        "is_sl": bool(p.get("is_sl", True)), "is_tgt": bool(p.get("is_tgt", True)),
    }


def base_rules(prm: dict) -> list:
    """The common SL / Target the order was sent with (AlgoDelta holds these for live orders)."""
    rules = []
    if prm.get("is_sl", True) and prm.get("sl") is not None:
        r = exit_rules.make_rule("sl", prm["sl_type"] if prm["sl_type"] in ("LTP", "POINT") else "POINT",
                                 prm["sl"], custom=False)
        if prm.get("trail") and prm.get("trigger") is not None and prm.get("gap") is not None:
            r["trail"] = {"trigger": prm["trigger"], "gap": prm["gap"], "step": prm.get("step") or 1}
        rules.append(r)
    if prm.get("is_tgt", True) and prm.get("tgt") is not None:
        rules.append(exit_rules.make_rule("tgt", prm["tgt_type"] if prm["tgt_type"] in ("LTP", "POINT") else "POINT",
                                          prm["tgt"], custom=False))
    return rules


def custom_rules(row) -> list:
    """Per-order SL / Target set in the app (Order Management before placing, Order Details after)."""
    return [r for r in (exit_rules.parse(row.get("c_sl")), exit_rules.parse(row.get("c_tgt"))) if r]


def simulate_exit(entry: float, entry_time: str, candles: list, prm: dict, now):
    """Dry-run exit with the order's common SL / Target / trailing SL (see exit_rules.evaluate).
    Returns (exit_price, "HH:MM", reason) or None while the trade is still open."""
    return exit_rules.evaluate(entry, entry_time, candles, base_rules(prm), now, eod=True)

def _keep(row, key):
    return row.get(key, "")


def _points(entry, exit_, ltp, qty_units):
    if entry is None:
        return {"entry": "--", "exit": "--", "points": "--", "pnl": "--"}
    pts = round(exit_ - entry, 2) if exit_ is not None else None      # Captured Points only once exited
    pnl = round(pts * qty_units, 2) if pts is not None and qty_units else None
    return {"entry": round(entry, 2), "exit": round(exit_, 2) if exit_ is not None else "--",
            "points": pts if pts is not None else "--", "pnl": pnl if pnl is not None else "--"}
