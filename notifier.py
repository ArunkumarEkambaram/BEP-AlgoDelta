"""
notifier.py — dispatches BEP Support alerts across UI toast and browser Notification.
"""
from nicegui import ui
import config


def _support_label(e: dict) -> str:
    how = "failed breakdown" if e.get("rule") == 1 else "touch and go"
    return (f"{e.get('index', 'NIFTY')} BEP Support {e['opt']}: {e['strike']} | BEP {e['bep']:.2f} | "
            f"close {e['close']:.2f} | {e['time']} ({how})")


def dispatch_support_alerts(events: list, log_fn=print):
    """Toast + browser notification per new BEP support row."""
    if not events:
        return
    if config.ALERTS_PAUSED:
        log_fn(f"Alerts paused: {len(events)} BEP support alert(s) not sent.")
        return
        
    for e in events:
        label = _support_label(e)
        ui.notify(label, type="positive", position="top", timeout=10000)
        ui.run_javascript(f"""
            if (Notification.permission === "granted") {{
                new Notification({(e.get('index', 'NIFTY') + " BEP Support " + e['opt'])!r}, {{ body: {label!r} }});
            }}
        """)

def dispatch_common_alert(r: dict, log_fn=print, market_open: bool = True):
    """Toast + browser notification when a Common Price Watch leg closes above its common price."""
    label = (f"{r['index']} {r['strike']}{r['opt']} closed above common price {r['price']:g}: "
             f"close {r['trig_close']:.2f} at {r['trig_time']} ({r['tf']} min). Use Place order to trade.")
    log_fn(f"COMMON PRICE: {label}")
    if config.ALERTS_PAUSED or not market_open:
        log_fn("Common price alert not shown (alerts paused or market closed).")
        return
    ui.notify(label, type="positive", position="top", timeout=15000)
    ui.run_javascript(f"""
        if (Notification.permission === "granted") {{
            new Notification({(r['index'] + " Common Price " + str(r['strike']) + r['opt'])!r}, {{ body: {label!r} }});
        }}
    """)
