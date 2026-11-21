"""
notifier.py - alert texts. The engine turns them into events; every open browser tab shows them as a toast
and a browser notification (see app.py).
"""


def support_label(e: dict) -> str:
    how = "failed breakdown" if e.get("rule") == 1 else "touch and go"
    return (f"{e.get('index', 'NIFTY')} BEP Support {e['opt']}: {e['strike']} | BEP {e['bep']:.2f} | "
            f"close {e['close']:.2f} | {e['time']} ({how})")


def cross_label(e: dict) -> str:
    """BEP Pair cross signal (pair_cross.py): one leg closed above its BEP, the other below its BEP."""
    up, dn = e["up"], e["dn"]
    also = f" | also {', '.join(e['also'])}" if e.get("also") else ""
    return (f"{e.get('index', 'NIFTY')} BEP Pair cross {e['time']}: BUY {up['strike']}{up['opt']} (closed "
            f"{up['close']:.2f} above BEP {up['bep']:.2f}) | opponent {dn['strike']}{dn['opt']} closed "
            f"{dn['close']:.2f} below BEP {dn['bep']:.2f} | ATM {e.get('atm')}{also}")


def common_label(r: dict) -> str:
    if r.get("trig_how") == "ltp":                    # Trigger on live LTP
        if r.get("kind") == "pair":
            opp = "PE" if r["opt"] == "CE" else "CE"
            line = (r["pe_price"] if r["opt"] == "CE" else r["ce_price"]) - r["buffer"]
            return (f"{r['index']} PAIR {r['ce_strike']}CE/{r['pe_strike']}PE: {r['strike']}{r['opt']} LTP above "
                    f"{r['price']:g} (LTP {r['trig_close']:.2f} at {r['trig_time']}) with {opp} LTP below {line:g}. "
                    "Use Place order to trade.")
        return (f"{r['index']} {r['strike']}{r['opt']} LTP above common price {r['price']:g}: "
                f"LTP {r['trig_close']:.2f} at {r['trig_time']}. Use Place order to trade.")
    if r.get("kind") == "pair":
        opp = "PE" if r["opt"] == "CE" else "CE"
        line = (r["pe_price"] if r["opt"] == "CE" else r["ce_price"]) - r["buffer"]
        return (f"{r['index']} PAIR {r['ce_strike']}CE/{r['pe_strike']}PE: {r['strike']}{r['opt']} closed above "
                f"{r['price']:g} (close {r['trig_close']:.2f} at {r['trig_time']}, {r['tf']} min) with {opp} below "
                f"{line:g}. Use Place order to trade.")
    return (f"{r['index']} {r['strike']}{r['opt']} closed above common price {r['price']:g}: "
            f"close {r['trig_close']:.2f} at {r['trig_time']} ({r['tf']} min). Use Place order to trade.")
