"""
notifier.py - alert texts. The engine turns them into events; every open browser tab shows them as a toast
and a browser notification (see app.py).
"""


def support_label(e: dict) -> str:
    how = "failed breakdown" if e.get("rule") == 1 else "touch and go"
    return (f"{e.get('index', 'NIFTY')} BEP Support {e['opt']}: {e['strike']} | BEP {e['bep']:.2f} | "
            f"close {e['close']:.2f} | {e['time']} ({how})")


def common_label(r: dict) -> str:
    return (f"{r['index']} {r['strike']}{r['opt']} closed above common price {r['price']:g}: "
            f"close {r['trig_close']:.2f} at {r['trig_time']} ({r['tf']} min). Use Place order to trade.")
