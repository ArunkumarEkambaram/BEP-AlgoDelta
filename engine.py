"""
engine.py - the app's single background engine.

Everything that is not drawing the screen lives here: the Upstox connection, the BEP Support scan, the 09:15
opening order, Order Management (common price + ⭐ rows), AlgoDelta orders and their Entry / Exit tracking, the log and the alerts.
It runs ONCE for the whole app (app.timer in app.py), however many browser tabs are open. The pages only read
its state; each change bumps a version number so a page knows when to redraw. Alerts are queued as events that
every open tab shows once.
"""
import csv
import os
from datetime import datetime

from nicegui import run

import bep
import config
import market_utils
import notifier
import order_bridge
import settings_store
import trade_tracker
import upstox_client
from bep_monitor import BepMonitor
from common_watch import CommonWatch  # noqa: F401  (also used for pair titles)

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER_FILE_COLUMNS = ["id", "time", "index", "opt", "strike", "kind", "bep", "ltp", "status", "detail", "payload",
                      "expiry", "qty", "exit", "exit_time", "exit_reason"]
ORDER_STATUS = {"dry_run": "DRY RUN", "sent": "SENT", "failed": "FAILED", "blocked": "BLOCKED"}
_LOCKING_STATUS = {"SENT": "sent", "DRY RUN": "dry_run", "FAILED": "failed"}


def _now():
    return datetime.now(market_utils.IST)


def _stamp():
    return datetime.now().strftime("%H:%M:%S")


class Engine:
    def __init__(self):
        self.settings_status = settings_store.load()
        config.AUTO_ORDER_DRY_RUN = True                     # always start in Dry run
        self.client = upstox_client.UpstoxClient(config.UPSTOX_ACCESS_TOKEN)
        self.monitors = {n: BepMonitor(n) for n in config.INDEXES}
        self.watches = {n: CommonWatch(n) for n in config.INDEXES}
        for w in self.watches.values():
            w.load()
        self.connected = False
        self.user_name = ""
        self.connection_text = "Not connected"
        self.status = "Waiting for a valid Upstox token (Setup page)"
        self.ltp = {n: None for n in config.INDEXES}
        self.log_lines = []
        self.events = []                                     # (seq, {"msg", "type", "title"})
        self.event_seq = 0
        self.versions = {k: 0 for k in ("board", "cards", "watch", "orders", "plan", "log", "settings", "bep")}
        self.bep_upload_text = {n: "" for n in config.INDEXES}
        self.scan_timer = None
        self._scan_busy = False
        self._open_busy = False
        self._trades_at = 0.0
        self.order_log = self._load_orders_today()
        self._restore_side_locks()
        self.log(f"App started. {self.settings_status} Dry run is ON.")

    # ------------------------------------------------------------------ helpers
    def bump(self, *keys):
        for k in keys:
            self.versions[k] += 1

    def log(self, msg: str):
        self.log_lines.append(f"[{_stamp()}] {msg}")
        del self.log_lines[:-1000]
        self.bump("log")

    def notify(self, msg: str, type_: str = "info", title: str = None):
        """Queues a toast (and a browser notification if `title`) for every open tab."""
        self.event_seq += 1
        self.events.append((self.event_seq, {"msg": msg, "type": type_, "title": title}))
        del self.events[:-50]

    def active(self):
        return [n for n in config.INDEXES if config.INDEXES[n]["enabled"]]

    def fetch_index_ltps(self, names):
        keys = {config.INDEXES[n]["index_key"]: n for n in names}
        ltp_map, err = self.client.fetch_ltp(list(keys))
        if not ltp_map:
            return {}, err
        out = {keys[k]: v for k, v in ltp_map.items() if k in keys}
        if not out and len(names) == 1 and len(ltp_map) == 1:
            out[names[0]] = next(iter(ltp_map.values()))
        return out, err

    # ------------------------------------------------------------------ orders file
    @staticmethod
    def _orders_file() -> str:
        return os.path.join(HERE, f"orders_{datetime.now().strftime('%Y-%m-%d')}.csv")

    def _load_orders_today(self) -> list:
        try:
            with open(self._orders_file(), newline="", encoding="utf-8") as f:
                rows = [dict(r) for r in csv.DictReader(f)]
        except OSError:
            return []
        for i, r in enumerate(rows):
            r["id"] = i                                       # older files have no id column
            for k in ("entry", "exit", "points", "pnl"):
                r.setdefault(k, "--")
            r.setdefault("ltp_live", "")
        return rows

    def _restore_side_locks(self):
        today = _now().strftime("%Y-%m-%d")
        for r in self.order_log:
            status = _LOCKING_STATUS.get(r.get("status"))
            if status and r.get("index") in self.monitors and r.get("opt") in ("CE", "PE") \
                    and r.get("kind", "Opening candle") == "Opening candle":
                mon = self.monitors[r["index"]]
                if (today, r["opt"]) not in mon.side_lock:
                    mon.lock_side(today, r["opt"], r.get("strike"), r.get("time", ""), status)

    def _save_order_row(self, row: dict):
        try:
            path = self._orders_file()
            new = not os.path.exists(path)
            fields = ORDER_FILE_COLUMNS
            if not new:
                with open(path, newline="", encoding="utf-8") as f:
                    fields = next(csv.reader(f), None) or ORDER_FILE_COLUMNS
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow({k: row.get(k, "") for k in fields})
        except OSError:
            pass

    def _rewrite_orders_file(self):
        """Rewrites today's orders file (used when a dry-run exit is found, so it survives a restart)."""
        try:
            path = self._orders_file()
            tmp = path + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=ORDER_FILE_COLUMNS, extrasaction="ignore")
                w.writeheader()
                for r in self.order_log:
                    row = {k: r.get(k, "") for k in ORDER_FILE_COLUMNS}
                    if r.get("status") != "DRY RUN":       # live exits always come from Upstox
                        row.update(exit="", exit_time="", exit_reason="")
                    w.writerow(row)
            os.replace(tmp, path)
        except OSError as ex:
            self.log(f"Could not update the orders file ({ex}).")

    def add_order_row(self, sig, res):
        import json
        row = {
            "id": len(self.order_log), "time": _stamp(), "index": sig["index"], "opt": sig["opt"],
            "strike": sig["strike"], "kind": sig.get("kind_label", "Opening candle"), "bep": round(float(sig["bep"]), 2),
            "ltp": round(float(sig["ltp"]), 2), "status": ORDER_STATUS.get(res["status"], res["status"]),
            "detail": res["detail"], "payload": json.dumps(res["payload"]),
            "expiry": sig.get("expiry") or "", "qty": config.AUTO_ORDER[sig["index"]]["qty"],
            "entry": "--", "exit": "--", "ltp_live": "", "points": "--", "pnl": "--",
        }
        self.order_log.append(row)
        self._save_order_row(row)
        self.bump("orders")

    def pnl_summary(self) -> dict:
        pts = [r["points"] for r in self.order_log if isinstance(r.get("points"), (int, float))]
        pnl = [r["pnl"] for r in self.order_log if isinstance(r.get("pnl"), (int, float))]
        return {"orders": len(self.order_log), "closed": len(pts), "points": round(sum(pts), 2),
                "pnl": round(sum(pnl), 2), "wins": sum(1 for p in pts if p > 0)}

    # ------------------------------------------------------------------ actions from the pages
    async def connect(self, token: str):
        token = (token or "").strip()
        if not token:
            self.connected, self.connection_text = False, "Token is empty"
            return False, self.connection_text
        self.client.access_token = token
        self.client.headers["Authorization"] = f"Bearer {token}"
        self.connection_text = "Testing..."
        ok, info = await run.io_bound(upstox_client.test_connection, token)
        self.connected = ok
        if ok:
            self.user_name, self.connection_text = info, f"Connected ({info})"
            settings_store.save_token(token, _now().strftime("%Y-%m-%d"))
            self.log("Upstox token verified and saved for today.")
        else:
            self.connection_text = f"Connection failed - {info}"
            self.log(f"Token test failed: {info}")
        self.bump("settings")
        return ok, self.connection_text

    async def auto_connect(self):
        """At start: reconnect with today's saved token, if there is one."""
        token = settings_store.load_token(_now().strftime("%Y-%m-%d"))
        if not token:
            self.log("No saved Upstox token for today - enter it on the Setup page.")
            return
        self.log("Reconnecting with today's saved Upstox token...")
        ok, text = await self.connect(token)
        if not ok:
            self.connection_text += " (saved token rejected - enter a new one)"

    def forget_token(self):
        settings_store.forget_token()
        self.log("Saved Upstox token deleted from this computer.")

    def upload_bep(self, name, data: bytes, fname: str):
        ok, msg, _warns = bep.load_csv(data, fname, name)
        self.bep_upload_text[name] = ("✅ " if ok else "❌ ") + msg
        self.log(f"{name} BEP upload ({fname}): {msg}")
        if ok:
            self.monitors[name].reset_backfill()
            self.log(f"{name} board reset; re-checking all candles since 09:15.")
            self.bump("board", "cards")
        self.bump("bep")
        return ok, msg

    def rescan(self):
        for mon in self.monitors.values():
            mon.reset_backfill()
        self.log("Manual rescan: re-scanning from 09:15 with the current window.")
        self.bump("board", "cards")

    def set_strike_count(self, n: int):
        config.STRIKES_EACH_SIDE = (int(n) - 1) // 2
        for mon in self.monitors.values():
            mon.force_recalc()
        self.log(f"Strike count set to {n}. {settings_store.save()}")
        self.bump("settings")

    def set_scan_interval(self, n: int):
        config.SCAN_INTERVAL_SECONDS = int(n)
        if self.scan_timer is not None:
            self.scan_timer.interval = int(n)
        self.log(f"Scan interval set to {n}s. {settings_store.save()}")
        self.bump("settings")

    def set_daily_limit(self, n: int):
        config.AUTO_ORDER_DAILY_LIMIT = max(1, int(n))
        settings_store.save()
        self.bump("settings")

    def toggle_alerts(self):
        config.ALERTS_PAUSED = not config.ALERTS_PAUSED
        self.log("Alerts PAUSED" if config.ALERTS_PAUSED else "Alerts RESUMED")
        self.bump("settings")

    def toggle_algo_pause(self):
        config.AUTO_ORDER_PAUSED = not config.AUTO_ORDER_PAUSED
        self.log("Algo trade PAUSED: no new entry orders." if config.AUTO_ORDER_PAUSED
                 else "Algo trade RESUMED: entry orders allowed again.")
        self.bump("settings")

    def set_dry_run(self, on: bool):
        config.AUTO_ORDER_DRY_RUN = bool(on)
        self.log("Dry run ON - orders are only logged." if on else "Dry run OFF - orders are LIVE.")
        self.bump("settings")

    def save_auto_order(self, name, template: dict, nums: dict, url: str, confirmed: bool) -> str:
        cfg = config.AUTO_ORDER[name]
        cfg["templates"]["strategy_order"] = template
        cfg.update(webhook_url=url, confirmed=bool(confirmed), **nums)
        saved = settings_store.save()
        self.log(f"{name} AlgoDelta settings saved. {saved}")
        self.bump("settings")
        return saved

    # ------------------------------------------------------------------ common price watch
    @staticmethod
    def default_target(name, kind: str):
        """(type, value) a new Order Management row starts with: kind 'same', 'pair' or 'star'."""
        cfg = config.AUTO_ORDER[name]
        return cfg.get("tgt_type", "POINT"), float(cfg.get(f"tgt_{kind}", cfg.get("tgt", 50)))

    def _stamp_target(self, name, rows, kind):
        tgt_type, tgt = self.default_target(name, kind)
        for r in rows:
            r.setdefault("tgt_type", tgt_type)
            r.setdefault("tgt", tgt)
        self.watches[name].save()

    def row_target(self, name, r):
        kind = {"star": "star", "pair": "pair"}.get(r.get("source"), "same")
        d_type, d_tgt = self.default_target(name, kind)
        return r.get("tgt_type") or d_type, float(r["tgt"]) if r.get("tgt") is not None else d_tgt

    def set_watch_target(self, name, row_id, tgt_type, tgt) -> bool:
        ok = self.watches[name].set_target(row_id, tgt_type, tgt)
        if ok:
            self.log(f"{name} Order Management row {row_id}: target set to {tgt:g} ({tgt_type}).")
        return ok

    def add_pair(self, name, ce_strike, pe_strike, ce_price, pe_price, buffer, tf):
        r = self.watches[name].add_pair(ce_strike, pe_strike, ce_price, pe_price, buffer, tf, _now())
        self._stamp_target(name, [r], "pair")
        self.log(f"{name} Order Management: pair added {CommonWatch.pair_title(r)}, buffer {buffer:g}, {tf} min.")
        self.bump("watch")

    def add_watch(self, name, strike, leg, price, tf):
        rows = self.watches[name].add(strike, leg, price, tf, _now())
        self._stamp_target(name, rows, "same")
        self.log(f"{name} common price watch added: "
                 + ", ".join(f"{r['strike']}{r['opt']} @ {r['price']:g} ({r['tf']} min)" for r in rows))
        self.bump("watch")

    def remove_watch(self, name, row_id):
        self.watches[name].remove(row_id)
        self.bump("watch")

    async def place_watch_order(self, name, row_id):
        cw, mon = self.watches[name], self.monitors[name]
        r = cw.get(row_id)
        if not r or r["status"] != "triggered" or r["order_status"] in ("SENT", "DRY RUN", "sending"):
            return None
        kind = {"star": "star", "pair": "pair"}.get(r.get("source"), "common")
        label = {"star": "Manual — ⭐ support", "pair": "Manual — pair",
                 "common": "Manual — common price"}[kind]
        tgt_type, tgt = self.row_target(name, r)
        sig = {"index": name, "opt": r["opt"], "strike": r["strike"], "bep": r["price"],
               "ltp": r["last_close"] if r["last_close"] is not None else r["trig_close"],
               "expiry": mon.expiry, "order_type": "strategy_order", "kind": kind,
               "kind_label": label, "time": _stamp(), "params": {"tgt": tgt, "tgt_type": tgt_type}}
        cw.set_order_status(row_id, "sending")
        self.bump("watch")
        res = await run.io_bound(order_bridge.send_order, sig)
        cw.set_order_status(row_id, ORDER_STATUS.get(res["status"], res["status"]))
        self.log(res["message"])
        self.add_order_row(sig, res)
        if r.get("kind") == "pair":
            r["order_id"] = self.order_log[-1]["id"]
            cw.save()
        self.bump("watch")
        return res

    async def handle_pair_exits(self, name):
        """Opponent SL of a pair: live -> AlgoDelta squareoff_position; dry run -> record the exit at the bought
        leg's close. Skipped if the order already has an exit (target / SL / trail hit first)."""
        cw, mon = self.watches[name], self.monitors[name]
        for ev in cw.pop_exits():
            row = next((o for o in self.order_log if o["id"] == ev.get("order_id")), None)
            opp = "PE" if ev["opt"] == "CE" else "CE"
            why = f"opponent {opp} closed {ev['opp_close']:.2f} at {ev['fail_time']}"
            if row is None:
                continue
            already = isinstance(row.get("exit"), (int, float)) or trade_tracker._f(row.get("exit")) is not None
            if already:
                self.log(f"Pair {CommonWatch.pair_title(ev)}: {why}, but the order had already exited - nothing to do.")
                status = "not needed"
            elif row.get("status") == "DRY RUN":
                row.update(exit=round(ev["exit_close"], 2), exit_time=ev["fail_time"], exit_reason="Opponent SL",
                           detail=f"{row.get('detail', '')} | Exit: Opponent SL {ev['fail_time']}".strip(" |"))
                res = order_bridge.send_squareoff(name, ev["opt"], ev["strike"], mon.expiry, why)
                self.log(res["message"])
                self.log(f"DRY RUN pair exit {ev['opt']} {ev['strike']} at {ev['exit_close']:.2f} ({why}).")
                self._rewrite_orders_file()
                status = "DRY RUN"
            elif row.get("status") == "SENT":
                res = await run.io_bound(order_bridge.send_squareoff, name, ev["opt"], ev["strike"], mon.expiry, why)
                self.log(res["message"])
                self.notify(res["message"][:160], "warning" if res["status"] == "sent" else "negative",
                            f"{name} square-off {ev['strike']}{ev['opt']}")
                row["detail"] = f"{row.get('detail', '')} | Square-off {res['status'].upper()} {_stamp()}".strip(" |")
                self._rewrite_orders_file()
                status = res["status"].upper()
            else:
                status = "not needed"
            live = cw.get(ev["id"])
            if live:
                live["squareoff"] = status
                cw.save()
            self.bump("watch", "orders")

    def _add_star_rows(self, name, events) -> bool:
        mon, cw, added = self.monitors[name], self.watches[name], False
        for e in events or []:
            if not e.get("in_window"):
                self.log(f"{name} ⭐ {e['strike']}{e['opt']} at {e['time']} not added to Order Management (outside ATM window).")
                continue
            if e["time"] == "09:15" and (e.get("day"), e["opt"]) in mon.side_lock:
                self.log(f"{name} ⭐ {e['strike']}{e['opt']} at 09:15 not added to Order Management "
                         f"({e['opt']} already has its 09:15 opening order).")
                continue
            row = cw.add_star(e)
            if row:
                self._stamp_target(name, [row], "star")
                added = True
                self.log(f"{name} ⭐ {e['strike']}{e['opt']} at {e['time']} added to Order Management "
                         f"(BEP {e['bep']:.2f}, close {e['close']:.2f}) - Place order is ready.")
        return added

    # ------------------------------------------------------------------ order sending
    async def dispatch_orders(self, name):
        mon = self.monitors[name]
        for sig in mon.pop_order_signals():
            res = await run.io_bound(order_bridge.send_order, sig)
            mon.record_order_result(sig, res["status"])
            self.log(res["message"])
            self.add_order_row(sig, res)
            self.notify(res["message"][:160], {"sent": "positive", "dry_run": "info"}.get(res["status"], "negative"))
        self.bump("plan")

    # ------------------------------------------------------------------ background loops
    async def scan(self):
        """Main scan, every SCAN_INTERVAL_SECONDS: index LTP, BEP Support board, cards, watch, orders tracking."""
        if not self.connected:
            self.status = "Waiting for a valid Upstox token (Setup page)"
            return
        active = self.active()
        if not active or self._scan_busy:
            return
        self._scan_busy = True
        try:
            ltps, err = await run.io_bound(self.fetch_index_ltps, active)
            self.status = ("Monitoring " + " + ".join(active)) if market_utils.is_market_open() else \
                f"Market closed (Mon–Fri {config.MARKET_OPEN}–{config.MARKET_CLOSE} IST)"
            for name in active:
                ltp = ltps.get(name)
                if ltp is None:
                    self.log(f"ERROR: {name} LTP unavailable ({err})")
                    continue
                self.ltp[name] = ltp
                mon = self.monitors[name]
                try:
                    res = await run.io_bound(mon.step, self.client, ltp, None, _now())
                    for msg in res["logs"]:
                        self.log(msg)
                    if res["board_changed"] or res["recalculated"]:
                        self.bump("board")
                    if res.get("first_updated") or res.get("latest_updated") or res["recalculated"]:
                        self.bump("cards")

                    alerts = mon.pop_support_alerts()
                    if alerts:
                        if config.ALERTS_PAUSED:
                            self.log(f"Alerts paused: {len(alerts)} BEP support alert(s) not shown.")
                        for e in alerts:
                            label = notifier.support_label(e)
                            self.log(label)
                            if not config.ALERTS_PAUSED:
                                self.notify(label, "positive", f"{e.get('index', name)} BEP Support {e['opt']}")
                    star_added = self._add_star_rows(name, alerts)
                    star_failed = self.watches[name].sync_star_failures(mon.support)

                    now = _now()
                    before = [(r["id"], r["status"], r["last_time"]) for r in self.watches[name].rows]
                    fired = await run.io_bound(self.watches[name].step, self.client, mon.expiry, now)
                    for r in fired:
                        label = notifier.common_label(r)
                        self.log("COMMON PRICE: " + label)
                        if config.ALERTS_PAUSED or not market_utils.is_market_open(now):
                            self.log("Common price alert not shown (alerts paused or market closed).")
                        else:
                            self.notify(label, "positive", f"{r['index']} Common Price {r['strike']}{r['opt']}")
                    after = [(r["id"], r["status"], r["last_time"]) for r in self.watches[name].rows]
                    if star_added or star_failed or fired or before != after:
                        self.bump("watch")

                    await self.handle_pair_exits(name)
                    await self.dispatch_orders(name)
                except Exception as ex:
                    self.log(f"{name} BEP monitor error: {ex}")
            await self.refresh_order_tracking()
        finally:
            self._scan_busy = False

    async def opening(self):
        """Every OPENING_TICK_SECONDS. Prep window (OPENING_PREP_START-09:15): read the pre-open price and prepare
        strikes / BEPs. 09:15:00-09:20: check only the prepared strikes and send at once."""
        if not self.connected or self._open_busy:
            return
        now = _now()
        h, m = (int(x) for x in config.OPENING_PREP_START.split(":"))
        start = now.replace(hour=h, minute=m, second=0, microsecond=0)
        first = now.replace(hour=9, minute=15, second=0, microsecond=0)
        end = now.replace(hour=9, minute=20, second=0, microsecond=0)
        if not (start <= now < end) or not market_utils.is_trading_day(now):
            return
        self._open_busy = True
        try:
            for name in self.active():
                mon, msgs = self.monitors[name], []
                try:
                    if now < first:
                        ltps, _err = await run.io_bound(self.fetch_index_ltps, [name])
                        if ltps.get(name) is not None:
                            self.ltp[name] = ltps[name]
                            await run.io_bound(mon.prepare_opening, self.client, ltps[name], now, msgs.append)
                    else:
                        await run.io_bound(mon.opening_tick, self.client, now, msgs.append)
                except Exception as ex:
                    msgs.append(f"{name} opening order error: {ex}")
                for msg in msgs:
                    self.log(msg)
                await self.dispatch_orders(name)
        finally:
            self._open_busy = False

    async def refresh_order_tracking(self):
        if not any(r.get("status") in trade_tracker.TRACKED for r in self.order_log):
            return
        trades = None
        now_ts = datetime.now().timestamp()
        if any(r.get("status") == "SENT" for r in self.order_log) and \
                now_ts - self._trades_at >= config.TRADES_REFRESH_SECONDS:
            trades, t_err = await run.io_bound(self.client.fetch_trades_for_day)
            self._trades_at = now_ts
            if trades is None:
                self.log(f"Upstox trade book unavailable ({t_err}); Entry/Exit not updated.")
        expiries = {n: self.monitors[n].expiry for n in self.monitors}
        try:
            updates, _err = await run.io_bound(trade_tracker.compute, self.client, self.order_log, expiries, trades)
        except Exception as ex:
            self.log(f"Order tracking error: {ex}")
            return
        if updates:
            new_exits = []
            for r in self.order_log:
                if r["id"] in updates:
                    u = updates[r["id"]]
                    if u.pop("exit_new", False):
                        u["detail"] = f"{r.get('detail', '')} | Exit: {u['exit_reason']} {u['exit_time']}".strip(" |")
                        new_exits.append(r)
                    r.update(u)
            for r in new_exits:
                self.log(f"DRY RUN {r['index']} {r['opt']} {r['strike']}: simulated exit {r['exit_reason']} at "
                         f"{r['exit_time']}, price {r['exit']} -> {r['points']} points, P&L {r['pnl']}")
            if new_exits:
                self._rewrite_orders_file()
            self.bump("orders")


engine = Engine()
