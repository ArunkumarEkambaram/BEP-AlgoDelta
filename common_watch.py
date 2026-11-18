"""
common_watch.py - Common Price Watch (manual trades, nothing is placed automatically).

You add a strike, a leg (Both / CE / PE), a common price and a timeframe (3 or 5 min). Each leg is
tracked on its own row. After every candle of that timeframe closes, the leg's close is compared with
the common price:
  - TRIGGERED: the close crosses ABOVE the common price (previous close <= common price, this close > it).
    The baseline is the last candle that closed before the row was added, so a leg that is already above
    must first close at or below, then cross. Fires once (alert + "Place order" button).
  - FAILED: after triggering, a later candle closes BELOW the common price. The row turns red, no alert.
Rows are kept for the day in common_watch_YYYY-MM-DD.json next to the app.
"""
import json
import os
from datetime import datetime, timedelta

import config
import market_utils

IST = market_utils.IST
FINALIZE_DELAY = timedelta(seconds=config.TRACK_FINALIZE_DELAY_SECONDS)


def _file(day: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), f"common_watch_{day}.json")


def _ts(c) -> datetime:
    t = datetime.fromisoformat(c[0])
    return t.astimezone(IST) if t.tzinfo else IST.localize(t)


class CommonWatch:
    def __init__(self, index: str):
        self.index = index
        self.day = None
        self.rows = []
        self._seq = 0

    # ------------------------------------------------------------------ persistence (same day only)
    def load(self, now=None):
        now = now or datetime.now(IST)
        self.day = now.strftime("%Y-%m-%d")
        self.rows, self._seq = [], 0
        try:
            with open(_file(self.day), encoding="utf-8") as f:
                data = json.load(f)
            self.rows = [r for r in data.get("rows", []) if r.get("index") == self.index]
            self._seq = max([r["id"] for r in self.rows], default=0)
        except (OSError, ValueError):
            pass

    def save(self):
        if not self.day:
            return
        try:
            others = []
            try:
                with open(_file(self.day), encoding="utf-8") as f:
                    others = [r for r in json.load(f).get("rows", []) if r.get("index") != self.index]
            except (OSError, ValueError):
                pass
            with open(_file(self.day), "w", encoding="utf-8") as f:
                json.dump({"rows": others + self.rows}, f, indent=1)
        except OSError:
            pass

    def _roll_day(self, now):
        if now.strftime("%Y-%m-%d") != self.day:
            self.load(now)

    # ------------------------------------------------------------------ rows
    def add(self, strike: int, leg: str, price: float, tf: int, now=None) -> list:
        now = now or datetime.now(IST)
        self._roll_day(now)
        added = []
        for opt in (("CE", "PE") if leg == "Both" else (leg,)):
            self._seq += 1
            row = {"id": self._seq, "index": self.index, "strike": int(strike), "opt": opt, "price": float(price),
                   "tf": int(tf), "added_at": now.isoformat(), "status": "watching", "baseline": None,
                   "last_done": None, "prev_close": None, "last_close": None, "last_time": "",
                   "trig_time": "", "trig_close": None, "fail_time": "", "fail_close": None, "order_status": ""}
            self.rows.append(row)
            added.append(row)
        self.save()
        return added

    def remove(self, row_id: int):
        self.rows = [r for r in self.rows if r["id"] != row_id]
        self.save()

    def get(self, row_id: int):
        return next((r for r in self.rows if r["id"] == row_id), None)

    def set_order_status(self, row_id: int, status: str):
        r = self.get(row_id)
        if r:
            r["order_status"] = status
            self.save()

    # ------------------------------------------------------------------ candle checks
    def step(self, client, expiry: str, now) -> list:
        """Checks every row against the candles that have closed since the last check.
        Returns a list of new TRIGGERED rows (copies) for alerting. Safe to call every scan."""
        self._roll_day(now)
        if not self.rows or not expiry:
            return []
        mapping, _ = market_utils.option_instrument_keys(client, expiry, config.INDEXES[self.index]["underlying_key"])
        mapping = mapping or {}
        triggered = []
        changed = False
        for r in self.rows:
            if r["status"] == "failed":
                continue
            tf = timedelta(minutes=r["tf"])
            ref = now - FINALIZE_DELAY
            minute = ref.minute - ref.minute % r["tf"]
            latest_closed_end = ref.replace(minute=minute, second=0, microsecond=0)   # end of the last closed candle
            if r["last_done"] and datetime.fromisoformat(r["last_done"]) + tf >= latest_closed_end:
                continue                                    # nothing new has closed yet
            ik = mapping.get(r["strike"], {}).get(r["opt"])
            if not ik:
                continue
            candles, _err = client.fetch_intraday_candles(ik, r["tf"])
            if not candles:
                continue
            added_at = datetime.fromisoformat(r["added_at"])
            closed = [c for c in candles if _ts(c) + tf <= ref]                       # completed candles only
            if r["baseline"] is None:
                before = [c for c in closed if _ts(c) + tf <= added_at]
                base = before[-1] if before else None
                r["baseline"] = base[0] if base else "none"
                r["prev_close"] = float(base[4]) if base else None
                r["last_done"] = base[0] if base else None
                changed = True
            for c in closed:
                if r["last_done"] and _ts(c) <= datetime.fromisoformat(r["last_done"]):
                    continue
                close, label = float(c[4]), (_ts(c) + tf).strftime("%H:%M")
                prev = r["prev_close"]
                if r["status"] == "watching" and prev is not None and prev <= r["price"] < close:
                    r.update(status="triggered", trig_time=label, trig_close=close)
                    triggered.append(dict(r))
                elif r["status"] == "triggered" and close < r["price"]:
                    r.update(status="failed", fail_time=label, fail_close=close)
                r.update(prev_close=close, last_close=close, last_time=label, last_done=c[0])
                changed = True
                if r["status"] == "failed":
                    break
        if changed:
            self.save()
        return triggered

    @staticmethod
    def status_text(r) -> str:
        if r["status"] == "triggered":
            return f"Triggered at {r['trig_time']}, close {r['trig_close']:.2f}"
        if r["status"] == "failed":
            return (f"Triggered at {r['trig_time']}, close {r['trig_close']:.2f} → "
                    f"failed at {r['fail_time']}, close {r['fail_close']:.2f}")
        return "Watching"
