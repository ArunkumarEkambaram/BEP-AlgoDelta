"""
notifier.py - alert texts. The engine turns them into events; every open browser tab shows them as a toast
and a browser notification (see app.py).
"""


def support_label(e: dict) -> str:
    how = "failed breakdown" if e.get("rule") == 1 else "touch and go"
    return (f"{e.get('index', 'NIFTY')} BEP Support {e['opt']}: {e['strike']} | BEP {e['bep']:.2f} | "
            f"close {e['close']:.2f} | {e['time']} ({how})")


def common_label(r: dict) -> str:
    if r.get("kind") == "pair":
        opp = "PE" if r["opt"] == "CE" else "CE"
        line = (r["pe_price"] if r["opt"] == "CE" else r["ce_price"]) - r["buffer"]
        return (f"{r['index']} PAIR {r['ce_strike']}CE/{r['pe_strike']}PE: {r['strike']}{r['opt']} closed above "
                f"{r['price']:g} (close {r['trig_close']:.2f} at {r['trig_time']}, {r['tf']} min) with {opp} below "
                f"{line:g}. Use Place order to trade.")
    return (f"{r['index']} {r['strike']}{r['opt']} closed above common price {r['price']:g}: "
            f"close {r['trig_close']:.2f} at {r['trig_time']} ({r['tf']} min). Use Place order to trade.")
