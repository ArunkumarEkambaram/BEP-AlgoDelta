"""
app.py — NiceGUI entry point for the BEP Support monitor.
"""
from datetime import datetime
from nicegui import ui, run

import csv
import json
import os
import config
import upstox_client
import notifier
import order_bridge
import trade_tracker
import market_utils
import export_utils
import bep
from bep_monitor import BepMonitor

monitors = {name: BepMonitor(name) for name in config.INDEXES}
client = upstox_client.UpstoxClient(config.UPSTOX_ACCESS_TOKEN)

log_lines = []
log_area = None
token_connected = False

BOARD_COLUMNS = [
    {"name": "strike", "label": "Strike", "field": "strike", "align": "left"},
    {"name": "ltp", "label": "LTP", "field": "ltp", "align": "right"},
    {"name": "bep", "label": "BEP", "field": "bep", "align": "right"},
    {"name": "time", "label": "Time", "field": "time", "align": "right"},
]

ORDER_COLUMNS = [
    {"name": "time", "label": "Time", "field": "time", "align": "left"},
    {"name": "index", "label": "Index", "field": "index", "align": "left"},
    {"name": "opt", "label": "Type", "field": "opt", "align": "left"},
    {"name": "strike", "label": "Strike", "field": "strike", "align": "left"},
    {"name": "kind", "label": "Order", "field": "kind", "align": "left"},
    {"name": "bep", "label": "BEP", "field": "bep", "align": "left"},
    {"name": "ltp", "label": "Signal LTP", "field": "ltp", "align": "left"},
    {"name": "entry", "label": "Entry", "field": "entry", "align": "left"},
    {"name": "exit", "label": "Exit", "field": "exit", "align": "left"},
    {"name": "ltp_live", "label": "LTP", "field": "ltp_live", "align": "left"},
    {"name": "points", "label": "Captured Points", "field": "points", "align": "left"},
    {"name": "pnl", "label": "P&L \u20b9", "field": "pnl", "align": "left"},
    {"name": "status", "label": "Status", "field": "status", "align": "left"},
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
]
# Downloads keep the JSON that was sent; the on-screen table does not show it.
ORDER_EXPORT_COLUMNS = [(c["name"], c["label"]) for c in ORDER_COLUMNS] + [("payload", "JSON")]
# Columns saved in today's orders_YYYY-MM-DD.csv (live columns are recalculated, not saved).
ORDER_FILE_COLUMNS = ["id", "time", "index", "opt", "strike", "kind", "bep", "ltp", "status", "detail", "payload",
                      "expiry", "qty"]
ORDER_STATUS = {"dry_run": "DRY RUN", "sent": "SENT", "failed": "FAILED", "blocked": "BLOCKED"}

BEP_EXPORT_COLUMNS = [
    ("index", "Index"), ("opt", "Type"), ("strike", "Strike"), ("first", "First of day"),
    ("bep", "BEP"), ("time", "Support time"), ("setup", "Setup"), ("fail_level", "Fail level"),
    ("status", "Status"), ("fail_time", "Failed at"), ("fail_close", "Fail close"), ("ltp", "LTP"),
]

SUPPORT_GREEN = ("rgb(200,230,201)", "#1b3d1e")
SUPPORT_RED = ("rgb(255,205,210)", "#7f1d1d")


def log(msg: str):
    log_lines.append(msg)
    del log_lines[:-200]
    if log_area is not None:
        log_area.set_content("\n".join(log_lines[-40:]))


def fetch_index_ltps(names):
    """Spot LTP of each index in `names` (one API call). Returns ({name: ltp}, error or None)."""
    keys = {config.INDEXES[n]["index_key"]: n for n in names}
    ltp_map, err = client.fetch_ltp(list(keys))
    if not ltp_map:
        return {}, err
    out = {keys[k]: v for k, v in ltp_map.items() if k in keys}
    if not out and len(names) == 1 and len(ltp_map) == 1:      # key came back in another format
        out[names[0]] = next(iter(ltp_map.values()))
    return out, err


def _orders_file() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), f"orders_{datetime.now().strftime('%Y-%m-%d')}.csv")


def _load_orders_today() -> list:
    try:
        with open(_orders_file(), newline="", encoding="utf-8") as f:
            rows = [dict(r) for r in csv.DictReader(f)]
    except OSError:
        return []
    for i, r in enumerate(rows):                      # live columns are recalculated after start
        r["id"] = i                                   # older files have no id column; ids follow file order
        for k in ("entry", "exit", "points", "pnl"):
            r.setdefault(k, "--")
        r.setdefault("ltp_live", "")
    return rows


order_log = _load_orders_today()

_LOCKING_STATUS = {"SENT": "sent", "DRY RUN": "dry_run", "FAILED": "failed"}


def _restore_side_locks():
    """After an app restart, keep CE / PE locked if today's orders file already has an order for that side."""
    today = datetime.now(market_utils.IST).strftime("%Y-%m-%d")
    for r in order_log:
        status = _LOCKING_STATUS.get(r.get("status"))
        if status and r.get("index") in monitors and r.get("opt") in ("CE", "PE"):
            mon = monitors[r["index"]]
            if (today, r["opt"]) not in mon.side_lock:          # first (earliest) order of the side wins
                mon.lock_side(today, r["opt"], r.get("strike"), r.get("time", ""), status)


_restore_side_locks()


def _save_order_row(row: dict):
    try:
        path = _orders_file()
        new = not os.path.exists(path)
        fields = ORDER_FILE_COLUMNS
        if not new:                                   # keep the header the file was started with
            with open(path, newline="", encoding="utf-8") as f:
                fields = next(csv.reader(f), None) or ORDER_FILE_COLUMNS
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in fields})
    except OSError:
        pass


@ui.page("/")
def main_page():
    global log_area, token_connected
    panels = {}
    scan_timer = None

    ui.add_head_html('''
        <style>
            .q-btn { border-radius: 8px !important; transition: all 0.2s ease-in-out !important; }
            .q-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 6px rgba(0,0,0,0.15); filter: brightness(0.95); }
        </style>
    ''')

    ui.run_javascript("""
        if (Notification.permission !== "granted" && Notification.permission !== "denied") {
            Notification.requestPermission();
        }
    """)

    with ui.left_drawer(value=True, fixed=False).classes("bg-gray-100 p-4") as drawer:
        ui.separator()
        ui.label("BEP files").classes("text-lg font-bold")

        def make_bep_upload(idx_name):
            async def handle_bep_upload(e):
                if hasattr(e, "file"):
                    data, fname = await e.file.read(), getattr(e.file, "name", "")
                else:
                    data, fname = e.content.read(), getattr(e, "name", "")
                ok, msg, warns = bep.load_csv(data, fname, idx_name)
                upload_label.set_text(("✅ " if ok else "❌ ") + msg)
                log(f"[{datetime.now().strftime('%H:%M:%S')}] {idx_name} BEP upload ({fname}): {msg}")
                status_label_bep.set_text(bep.status_text(idx_name))
                if ok:
                    monitors[idx_name].reset_backfill()
                    if idx_name in panels:
                        panels[idx_name]["render_all"]()
                    log(f"[{datetime.now().strftime('%H:%M:%S')}] {idx_name} board reset; re-checking all candles since 09:15.")
                try:
                    uploader.reset()
                except Exception:
                    pass

            ui.label(idx_name).classes("text-sm font-bold")
            uploader = ui.upload(on_upload=handle_bep_upload, auto_upload=True, max_files=1).props("accept=.csv").classes("hidden")
            ui.button(f"Upload {idx_name} BEP CSV", icon="upload_file", on_click=lambda: uploader.run_method('pickFiles')).classes("w-full")
            upload_label = ui.label("")
            status_label_bep = ui.label(bep.status_text(idx_name)).classes("text-sm text-gray-600")

        for _idx in config.INDEXES:
            make_bep_upload(_idx)

        ui.separator()
        ui.label("Upstox").classes("text-lg font-bold")
        with ui.column().classes("w-full gap-1"):
            token_input = ui.input("Upstox Access Token", value=config.UPSTOX_ACCESS_TOKEN, password=True, password_toggle_button=True).classes("w-full")
            connection_label = ui.label("Status: not connected" if not config.UPSTOX_ACCESS_TOKEN else "Status: unverified")

        async def save_and_test_token():
            global token_connected
            token = token_input.value.strip()
            if not token:
                connection_label.set_text("Status: token is empty")
                token_connected = False
                return
            client.access_token = token
            client.headers["Authorization"] = f"Bearer {token}"
            connection_label.set_text("Status: testing...")
            ok, info = await run.io_bound(upstox_client.test_connection, token)
            if ok:
                connection_label.set_text(f"Status: connected ({info})")
                token_connected = True
                log(f"[{datetime.now().strftime('%H:%M:%S')}] Upstox token saved and verified.")
            else:
                connection_label.set_text(f"Status: connection failed — {info}")
                token_connected = False
                log(f"[{datetime.now().strftime('%H:%M:%S')}] Token test failed: {info}")

        ui.button("Save & Test Connection", on_click=save_and_test_token).classes("w-full")

        ui.separator()
        ui.label("Scanner").classes("text-lg font-bold")
        with ui.column().classes("w-full gap-1"):
            default_total_strikes = 2 * config.STRIKES_EACH_SIDE + 1
            strike_slider = ui.slider(min=1, max=11, step=2, value=default_total_strikes).classes("w-full")
            strike_count_label = ui.label(f"Currently: {default_total_strikes} strikes (center ± {config.STRIKES_EACH_SIDE})")

        def save_strike_count():
            n = int(strike_slider.value)
            config.STRIKES_EACH_SIDE = (n - 1) // 2
            strike_count_label.set_text(f"Currently: {n} strikes (center ± {config.STRIKES_EACH_SIDE})")
            log(f"[{datetime.now().strftime('%H:%M:%S')}] Strike count set to {n}.")

        ui.button("Save Strike Count", on_click=save_strike_count).classes("w-full")
        
        def force_rescan():
            for mon in monitors.values():
                mon.reset_backfill()
            log(f"[{datetime.now().strftime('%H:%M:%S')}] 🚨 Manual rescan triggered: The app is re-scanning from 09:15 with the current window.")
            
        ui.button("Rescan from 09:15", on_click=force_rescan, color="orange") \
            .classes("w-full").props("icon=restart_alt")

        with ui.column().classes("w-full gap-1"):
            scan_interval_input = ui.number("Scan interval (seconds)", value=config.SCAN_INTERVAL_SECONDS, min=1, step=1).classes("w-full")
            scan_interval_label = ui.label(f"Currently: every {config.SCAN_INTERVAL_SECONDS}s")

        def save_scan_interval():
            try:
                n = int(scan_interval_input.value)
            except (TypeError, ValueError):
                scan_interval_label.set_text("Enter a whole number of seconds.")
                return
            if n < 1:
                scan_interval_label.set_text("Must be at least 1 second — not applied.")
                return
            config.SCAN_INTERVAL_SECONDS = n
            scan_timer.interval = n
            scan_interval_label.set_text(f"Currently: every {n}s")
            log(f"[{datetime.now().strftime('%H:%M:%S')}] Scan interval set to {n}s.")

        ui.button("Save Scan Interval", on_click=save_scan_interval).classes("w-full")

    def apply_alert_state():
        paused = config.ALERTS_PAUSED
        alert_btn.set_text("Resume alerts" if paused else "Pause alerts")
        alert_btn.props("color=green icon=notifications_active" if paused else "color=primary icon=notifications_off")
        paused_badge.set_visibility(paused)

    def toggle_alerts():
        config.ALERTS_PAUSED = not config.ALERTS_PAUSED
        apply_alert_state()
        if config.ALERTS_PAUSED:
            ui.notify("Alerts paused", type="warning")
            log(f"[{datetime.now().strftime('%H:%M:%S')}] Alerts PAUSED")
        else:
            ui.notify("Alerts resumed", type="positive")
            log(f"[{datetime.now().strftime('%H:%M:%S')}] Alerts RESUMED")

    with ui.row().classes("items-center gap-4"):
        ui.button(icon="menu", on_click=drawer.toggle).props("flat round")
        ui.label("BEP Support Monitor").classes("text-2xl font-bold")
        alert_btn = ui.button("Pause alerts", icon="notifications_off", on_click=toggle_alerts)
        paused_badge = ui.badge("ALERTS PAUSED").props("color=red")
        apply_alert_state()

        def on_index_toggle(idx_name, enabled):
            config.INDEXES[idx_name]["enabled"] = bool(enabled)
            if idx_name in panels:
                panels[idx_name]["section"].set_visibility(bool(enabled))
            if enabled:
                monitors[idx_name].reset_backfill()
                monitors[idx_name].force_recalc()
            log(f"[{datetime.now().strftime('%H:%M:%S')}] {idx_name} {'ENABLED' if enabled else 'DISABLED'}")

        for _idx, _cfg in config.INDEXES.items():
            ui.checkbox(_idx, value=_cfg["enabled"], on_change=lambda ev, n=_idx: on_index_toggle(n, ev.value))

        auto_badge = ui.badge("").props("color=orange")

        def apply_auto_state():
            paused = config.AUTO_ORDER_PAUSED
            algo_pause_btn.set_text("Resume algo trade" if paused else "Pause algo trade")
            algo_pause_btn.props("icon=play_arrow color=green" if paused else "icon=pause color=orange")
            
            if paused:
                auto_badge.set_text("ALGO PAUSED")
                auto_badge.props("color=grey-8")
            else:
                auto_badge.set_text("ALGO TRADING \u00b7 DRY RUN" if config.AUTO_ORDER_DRY_RUN else "ALGO TRADING \u00b7 LIVE")
                auto_badge.props("color=orange" if config.AUTO_ORDER_DRY_RUN else "color=red")
            auto_badge.set_visibility(True)

        def toggle_algo_pause():
            config.AUTO_ORDER_PAUSED = not config.AUTO_ORDER_PAUSED
            apply_auto_state()
            msg = ("Algo trade PAUSED: no new entry orders." if config.AUTO_ORDER_PAUSED else "Algo trade RESUMED: new stars can place orders again.")
            log(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            ui.notify(msg, type="warning" if config.AUTO_ORDER_PAUSED else "positive", position="top")

        def on_dry_run_toggle(enabled):
            if enabled:
                config.AUTO_ORDER_DRY_RUN = True
                apply_auto_state()
                return
            with ui.dialog() as dlg, ui.card():
                ui.label("Turn OFF dry run? Auto orders will be sent to AlgoDelta and placed with real money.")

                def go_live():
                    config.AUTO_ORDER_DRY_RUN = False
                    apply_auto_state()
                    log(f"[{datetime.now().strftime('%H:%M:%S')}] Dry run OFF - auto orders are LIVE")
                    dlg.close()

                with ui.row():
                    ui.button("Cancel", on_click=dlg.close)
                    ui.button("Yes, go live", on_click=go_live).props("color=red")
            dlg.on("hide", lambda: dry_cb.set_value(config.AUTO_ORDER_DRY_RUN))
            dlg.open()

        algo_pause_btn = ui.button("Pause algo trade", on_click=toggle_algo_pause).props("icon=pause color=orange")
        
        dry_cb = ui.checkbox("Dry run", value=config.AUTO_ORDER_DRY_RUN, on_change=lambda ev: on_dry_run_toggle(ev.value)) \
            .tooltip("Dry run = only log the JSON, send nothing")
        ui.number("Max orders/day", value=config.AUTO_ORDER_DAILY_LIMIT, min=1, precision=0, step=1,
                  on_change=lambda ev: setattr(config, "AUTO_ORDER_DAILY_LIMIT", int(ev.value or 1))).classes("w-36").props("dense")
        apply_auto_state()

    ui.separator()
    def download_bep_xlsx():
        rows = []
        for n in config.INDEXES:
            if config.INDEXES[n]["enabled"]:
                rows.extend(monitors[n].export_rows())
        if not rows:
            ui.notify("No BEP Support rows to export yet", type="warning")
            return
        ui.download(export_utils.build_xlsx(rows, BEP_EXPORT_COLUMNS),
                    f"bep_support_{datetime.now().strftime('%Y-%m-%d')}.xlsx")

    with ui.row().classes("items-center gap-6"):
        status_label = ui.label("Status: waiting for valid token")
        ui.button("Download BEP Support XLSX", icon="download", on_click=download_bep_xlsx).props("dense")
    polling = {"busy": False, "trades_at": 0.0}
    ui.label("BEP Support Boards: Green = a green candle touched BEP (low <= BEP) and closed above it. "
             "Red = one of the next 3 candles (15 min) closed below the fail level (the flush candle's low if a failed-breakdown "
             "setup stood behind it, otherwise the trigger candle's own low); after that the row stays green. "
             "\u2b50 = first support of the day for that strike. Only the first support of the day for a strike raises a notification.").classes("text-xs text-gray-500")

    def build_panel(name):
        mon = monitors[name]
        section = ui.column().classes("w-full gap-2")
        with section:
            ui.separator()
            with ui.row().classes("gap-6 items-center"):
                ui.label(name).classes("text-xl font-bold")
                ltp_label = ui.label(f"{name} LTP: --")
                window_label = ui.label("Window: --")

            first_cards, latest_cards = {}, {}
            with ui.row().classes("gap-4"):
                for kind in ("CE", "PE"):
                    card = ui.card().classes("w-80 rounded-xl shadow-md")
                    with card:
                        with ui.row().classes("items-center justify-between w-full no-wrap"):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.icon("circle", color="green" if kind == "CE" else "red").classes("text-3xl")
                                ui.label(f"First {kind}").classes("text-gray-600")
                            badge = ui.badge("--").props("color=grey")
                        name_label = ui.label("--").classes("text-xl font-bold")
                        detail_label = ui.label("Waiting for first candle").classes("text-sm text-gray-500")
                    first_cards[kind] = {"card": card, "badge": badge, "name": name_label, "detail": detail_label}

                for kind in ("CE", "PE"):
                    card = ui.card().classes("w-80 rounded-xl shadow-md")
                    with card:
                        with ui.row().classes("items-center justify-between w-full no-wrap"):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.icon("circle", color="green" if kind == "CE" else "red").classes("text-3xl")
                                ui.label(f"Latest Support {kind}").classes("text-gray-600")
                            badge = ui.badge("--").props("color=grey")
                        name_label = ui.label(f"NO {kind}").classes("text-xl font-bold")
                        detail_label = ui.label("").classes("text-sm text-gray-500")
                    latest_cards[kind] = {"card": card, "badge": badge, "name": name_label, "detail": detail_label}

            board_tables = {}
            with ui.row().classes("w-full no-wrap items-start gap-4"):
                ad_cfg = config.AUTO_ORDER[name]
                ad_col = ui.column().classes("gap-2").style("flex: 2 1 0; min-width: 0")
                with ad_col:
                    ui.label(f"{name} \u2014 AlgoDelta order").classes("text-md font-bold")
                    ad_url = ui.input("Webhook URL (AlgoDelta: Copy Webhook)", value=ad_cfg["webhook_url"],
                                      password=True, password_toggle_button=True).classes("w-full")
                    
                    # JSON template: edited in a popup, opened from the "JSON template" link.
                    with ui.row().classes("items-center gap-2"):
                        ui.button("JSON template", icon="edit", on_click=lambda: tpl_dialog.open()) \
                            .props("flat dense no-caps color=primary").classes("underline")
                        tpl_tag = ui.badge("default").props("outline color=grey-7")

                    with ui.dialog() as tpl_dialog, ui.card().style("width: 720px; max-width: 95vw"):
                        ui.label(f"{name} \u2014 JSON template (strategy_order)").classes("text-lg font-bold")
                        ad_template = ui.textarea(value=json.dumps(ad_cfg["templates"]["strategy_order"], indent=2)) \
                            .classes("w-full").props("outlined input-style='font-family: monospace; font-size: 12px' rows=18")
                        ui.label("Placeholders: {symbol} {opt} {signal} {qty} {tgt} {tgt_type} {sl} {sl_type} {strike} {expiry} {index} {bep} {ltp} "
                                 "{exit_on_opposite} {is_trail} {trail_type} {trail_trigger} {trail_point} {trail_gap}. "
                                 "{symbol} = index + expiry + strike + CE/PE, e.g. NIFTY17NOV2625400CE. {signal} = UP for CE, DOWN for PE. "
                                 "Target/SL/trail values come from the controls in the AlgoDelta box; exit_on_opposite, is_trail_set and the trail_* "
                                 "keys are always set from those controls, whatever this template says.").classes("text-xs text-gray-500")
                        tpl_status = ui.label("").classes("text-sm")

                        def reset_template():
                            ad_template.set_value(json.dumps(config._STRATEGY_ORDER, indent=2))
                            tpl_status.set_text("Reset to the default template (not saved yet; click Save).")

                        def save_from_dialog():
                            save_auto_order_settings()
                            tpl_status.set_text(ad_status.text)

                        with ui.row().classes("w-full gap-2 justify-end"):
                            ui.button("Reset to default", icon="restart_alt", on_click=reset_template).props("flat color=orange")
                            ui.button("Preview JSON", on_click=lambda: preview_auto_order()).props("outline")
                            ui.button("Save", on_click=save_from_dialog)
                            ui.button("Close", on_click=tpl_dialog.close).props("flat")

                    def update_tpl_tag():
                        try:
                            cur = json.loads(ad_template.value)
                        except ValueError:
                            cur = None
                        text = "default" if cur == config._STRATEGY_ORDER else "edited"
                        if cur != ad_cfg["templates"]["strategy_order"]:
                            text += " \u00b7 not saved"
                        tpl_tag.set_text(text)
                        tpl_tag.props("outline color=" + ("grey-7" if text == "default" else "orange"))

                    update_tpl_tag()
                    ad_template.on_value_change(lambda ev: update_tpl_tag())

                    with ui.row().classes("w-full gap-2 no-wrap items-center"):
                        ad_qty = ui.number("Quantity", value=ad_cfg["qty"], min=1, precision=0, step=1).classes("flex-1")
                        
                    with ui.row().classes("w-full gap-2 no-wrap items-center"):
                        ad_tgt_type = ui.select(["POINT", "LTP"], value=ad_cfg.get("tgt_type", "POINT"), label="Target Type").classes("flex-1")
                        ad_tgt = ui.number("Target Value", value=ad_cfg["tgt"], min=0, step=1).classes("flex-1")
                        
                    with ui.row().classes("w-full gap-2 no-wrap items-center"):
                        ad_sl_type = ui.select(["POINT", "LTP"], value=ad_cfg.get("sl_type", "POINT"), label="Stop Loss Type").classes("flex-1")
                        ad_sl = ui.number("Stop Loss Value", value=ad_cfg["sl"], min=0, step=1).classes("flex-1")

                    ad_max_above = ui.number("09:15 order: max points above BEP (skip at or above)",
                                             value=ad_cfg.get("max_above_bep", 15), min=0, step=1).classes("w-full")
                    ad_exit_opp = ui.switch("Exit on opposite signal", value=ad_cfg.get("exit_on_opposite", False))
                    ad_trail = ui.switch("Trailing SL", value=ad_cfg.get("trail", False))
                    with ui.row().classes("w-full gap-2 no-wrap items-center"):
                        ad_trail_type = ui.select(["POINT", "LTP"], value=ad_cfg.get("trail_type", "LTP"), label="Trail Type").classes("flex-1")
                        ad_trail_trigger = ui.number("Trail Trigger", value=ad_cfg.get("trail_trigger", 20), min=0, step=1).classes("flex-1")
                        ad_trail_point = ui.number("Trail Point", value=ad_cfg.get("trail_point", 1), min=0, step=1).classes("flex-1")
                        ad_trail_gap = ui.number("Trail Gap", value=ad_cfg.get("trail_gap", 20), min=0, step=1).classes("flex-1")
                    for _w in (ad_trail_type, ad_trail_trigger, ad_trail_point, ad_trail_gap):
                        _w.bind_enabled_from(ad_trail, "value")

                    ad_confirm = ui.checkbox("I checked this JSON against the Syntax Generator", value=ad_cfg["confirmed"])
                    ad_status = ui.label("")
                    plan_label = ui.label(mon.plan_text()).classes("text-sm text-indigo-8")
                    side_lock_label = ui.label(mon.side_status_text()).classes("text-sm font-medium text-indigo-8")

                    ad_template.on_value_change(lambda ev: ad_confirm.set_value(False))

                    def _parse_template():
                        try:
                            obj = json.loads(ad_template.value)
                        except ValueError as ex:
                            return None, f"JSON error: {ex}"
                        if not isinstance(obj, dict):
                            return None, "The template must be one JSON object { ... }."
                        if obj.get("type") != "strategy_order":
                            return None, f"\"type\" must be \"strategy_order\" (found {obj.get('type')!r})."
                        return obj, ""

                    def _numbers():
                        def num(v):
                            return None if v is None else (int(v) if float(v) == int(v) else float(v))
                        tgt, sl, qty = num(ad_tgt.value), num(ad_sl.value), num(ad_qty.value)
                        if tgt is None or sl is None or tgt <= 0 or sl <= 0:
                            return None, "Target and SL must be numbers above 0."
                        if qty is None or qty < 1 or qty != int(qty):
                            return None, "Quantity must be a whole number of at least 1."
                        max_above = num(ad_max_above.value)
                        if max_above is None or max_above <= 0:
                            return None, "Max points above BEP must be a number above 0."
                        trail = bool(ad_trail.value)
                        t_trig, t_point, t_gap = num(ad_trail_trigger.value), num(ad_trail_point.value), num(ad_trail_gap.value)
                        if trail:
                            if None in (t_trig, t_point, t_gap) or t_trig <= 0 or t_point <= 0 or t_gap <= 0:
                                return None, "Trail Trigger, Trail Point and Trail Gap must be numbers above 0."
                            if ad_trail_type.value == "POINT" and t_gap >= t_trig:
                                return None, "With Trail Type POINT, Trail Gap must be smaller than Trail Trigger."
                        return {"tgt": tgt, "sl": sl, "qty": int(qty), "tgt_type": ad_tgt_type.value, "sl_type": ad_sl_type.value,
                                "exit_on_opposite": bool(ad_exit_opp.value), "trail": trail, "max_above_bep": max_above,
                                "trail_type": ad_trail_type.value,
                                "trail_trigger": t_trig if t_trig is not None else ad_cfg.get("trail_trigger", 20),
                                "trail_point": t_point if t_point is not None else ad_cfg.get("trail_point", 1),
                                "trail_gap": t_gap if t_gap is not None else ad_cfg.get("trail_gap", 20)}, ""

                    def save_auto_order_settings():
                        obj, err = _parse_template()
                        if obj is None:
                            ad_status.set_text("\u274c " + err)
                            return
                        nums, err = _numbers()
                        if nums is None:
                            ad_status.set_text("\u274c " + err)
                            return
                        url = (ad_url.value or "").strip()
                        if url and not url.lower().startswith("https://"):
                            ad_status.set_text("\u274c The webhook URL must start with https://")
                            return
                        ad_cfg["templates"]["strategy_order"] = obj
                        update_tpl_tag()
                        ad_cfg.update(webhook_url=url, confirmed=bool(ad_confirm.value), **nums)
                        trail_txt = (f"trail ON ({nums['trail_type']}: trigger {nums['trail_trigger']}, point {nums['trail_point']}, "
                                     f"gap {nums['trail_gap']})" if nums["trail"] else "trail OFF")
                        ad_status.set_text(f"\u2705 Saved: target {nums['tgt']} ({nums['tgt_type']}), SL {nums['sl']} ({nums['sl_type']}), qty {nums['qty']}; "
                                           f"{trail_txt}; exit on opposite {'ON' if nums['exit_on_opposite'] else 'OFF'}; "
                                           f"09:15 order only if LTP is < {nums['max_above_bep']} above BEP; "
                                           f"webhook {'set' if url else 'NOT set'}; JSON {'confirmed' if ad_confirm.value else 'NOT confirmed'} "
                                           f"(live orders need both). Lasts until the app restarts.")
                        log(f"[{datetime.now().strftime('%H:%M:%S')}] {name} AlgoDelta settings saved.")

                    def preview_auto_order():
                        obj, err = _parse_template()
                        if obj is None:
                            ad_status.set_text("\u274c " + err)
                            return
                        nums, err = _numbers()
                        if nums is None:
                            ad_status.set_text("\u274c " + err)
                            return
                        sample = {"index": name, "opt": "CE", "strike": 25400, "expiry": "2026-11-17", "bep": 100.0, "ltp": 101.5}
                        payload = order_bridge.build_payload(sample, obj, nums)
                        with ui.dialog() as dlg, ui.card():
                            ui.label(f"Sample order JSON ({name} 25400 CE, expiry 17 Nov 2026)").classes("font-bold")
                            ui.code(json.dumps(payload, indent=2), language="json")
                            ui.button("Close", on_click=dlg.close)
                        dlg.open()

                    with ui.row().classes("w-full gap-2"):
                        ui.button("Save", on_click=save_auto_order_settings)
                        ui.button("Preview JSON", on_click=preview_auto_order).props("outline")

                for opt in ("CE", "PE"):
                    with ui.column().classes("gap-2").style("flex: 1 1 0; min-width: 0"):
                        ui.label(f"{name} BEP Support — {opt}").classes("text-md font-bold")
                        table = ui.table(columns=BOARD_COLUMNS, rows=[], row_key="id").classes("w-full").props("dense flat bordered").style("max-height: 640px; overflow-y: auto")
                        table.add_slot(
                            "body",
                            """
                            <q-tr :props="props" :style="props.row.bg ? {backgroundColor: props.row.bg, color: props.row.fg} : {}">
                              <q-td key="strike" :props="props"><span class="text-weight-bold">{{ props.row.strike }}</span><span v-if="props.row.first" style="margin-left:6px">⭐<q-tooltip>First support of the day for this strike</q-tooltip></span></q-td>
                              <q-td key="ltp" :props="props">{{ props.row.ltp }}</q-td>
                              <q-td key="bep" :props="props">{{ props.row.bep }}</q-td>
                              <q-td key="time" :props="props">{{ props.row.time }}</q-td>
                            </q-tr>
                            """,
                        )
                        board_tables[opt] = table

            def render_board():
                view = mon.board_view()
                for opt, table in board_tables.items():
                    rows = []
                    for r in view.get(opt, []):
                        row = dict(r)
                        row["bg"], row["fg"] = SUPPORT_GREEN if r["kind"] == "green" else SUPPORT_RED
                        rows.append(row)
                    table.rows = rows
                    table.update()

            def _fill_card(w, kind, leg, state_colours):
                w["card"].classes(remove="bg-green-2 bg-red-2")
                if not leg:
                    w["name"].set_text(f"NO {kind}")
                    w["detail"].set_text("Waiting for first candle" if state_colours is None else "")
                    w["badge"].set_text("--")
                    w["badge"].props("color=grey")
                    return
                w["name"].set_text(f"{name} {leg['strike']}{kind}")
                ltp, level = leg.get("ltp"), leg.get("bep")
                w["detail"].set_text(f"BEP {level:.2f} · LTP {ltp:.2f}" if ltp is not None else f"BEP {level:.2f} · LTP --")
                if ltp is not None:
                    gap = ltp - level
                    w["badge"].set_text(f"{gap:+.2f}")
                    w["badge"].props(f"color={'green' if gap >= 0 else 'red'}")
                else:
                    w["badge"].set_text("--")
                    w["badge"].props("color=grey")
                w["card"].classes(add="bg-green-2" if (state_colours is None or leg.get("state") == "green") else "bg-red-2")

            def render_first_cards():
                view = mon.first_view or {}
                for kind, w in first_cards.items():
                    _fill_card(w, kind, view.get(kind), None)

            def render_latest_cards():
                view = mon.latest_view or {}
                for kind, w in latest_cards.items():
                    _fill_card(w, kind, view.get(kind), True)

            def render_all():
                render_board()
                render_first_cards()
                render_latest_cards()

            section.set_visibility(config.INDEXES[name]["enabled"])
            return {"section": section, "ltp_label": ltp_label, "window_label": window_label,
                    "render_board": render_board, "render_first": render_first_cards,
                    "render_latest": render_latest_cards, "render_all": render_all,
                    "render_locks": lambda: (side_lock_label.set_text(mon.side_status_text()),
                                             plan_label.set_text(mon.plan_text()))}

    for _idx in config.INDEXES:
        panels[_idx] = build_panel(_idx)

    ui.separator()
    ui.label("AlgoDelta orders \u2014 dry run and live").classes("text-md font-bold")
    orders_table = ui.table(columns=ORDER_COLUMNS, rows=list(reversed(order_log)), row_key="id").classes("w-full").props("dense")
    orders_table.add_slot("body-cell-status", '''
        <q-td key="status" :props="props">
            <q-badge :color="props.value === 'SENT' ? 'green' : props.value === 'DRY RUN' ? 'blue' : props.value === 'FAILED' ? 'red' : 'orange'">{{ props.value }}</q-badge>
        </q-td>''')
    for _col in ("points", "pnl"):                    # green when >= 0, red when < 0
        orders_table.add_slot(f"body-cell-{_col}", f'''
        <q-td key="{_col}" :props="props" :class="typeof props.value === 'number' ? (props.value >= 0 ? 'text-green-8 text-weight-bold' : 'text-red-8 text-weight-bold') : ''">{{{{ props.value }}}}</q-td>''')
    orders_table.add_slot("body-cell-detail", '''
        <q-td key="detail" :props="props" style="max-width: 260px; white-space: normal; word-break: break-word">{{ props.value }}</q-td>''')

    def add_order_row(sig, res):
        row = {
            "id": len(order_log), "time": datetime.now().strftime("%H:%M:%S"), "index": sig["index"], "opt": sig["opt"],
            "strike": sig["strike"], "kind": "Opening candle", "bep": round(float(sig["bep"]), 2),
            "ltp": round(float(sig["ltp"]), 2),
            "status": ORDER_STATUS.get(res["status"], res["status"]), "detail": res["detail"],
            "payload": json.dumps(res["payload"]),
            "expiry": sig.get("expiry") or "", "qty": config.AUTO_ORDER[sig["index"]]["qty"],
            "entry": "--", "exit": "--", "ltp_live": "", "points": "--", "pnl": "--",
        }
        order_log.append(row)
        _save_order_row(row)
        orders_table.rows = list(reversed(order_log))
        orders_table.update()

    def download_orders_csv():
        ui.download(export_utils.build_csv(list(order_log), ORDER_EXPORT_COLUMNS), f"algodelta_orders_{datetime.now().strftime('%Y-%m-%d')}.csv")

    def download_orders_xlsx():
        ui.download(export_utils.build_xlsx(list(order_log), ORDER_EXPORT_COLUMNS), f"algodelta_orders_{datetime.now().strftime('%Y-%m-%d')}.xlsx")

    with ui.row().classes("gap-3"):
        ui.button("Download CSV", on_click=download_orders_csv)
        ui.button("Download XLSX", on_click=download_orders_xlsx)

    ui.separator()
    log_area = ui.markdown("")

    async def poll():
        if not token_connected:
            status_label.set_text("Status: waiting for valid token")
            return
        active = [n for n in config.INDEXES if config.INDEXES[n]["enabled"]]
        if not active:
            status_label.set_text("Status: no index selected (tick NIFTY at the top)")
            return
        if polling["busy"]:
            return
        polling["busy"] = True
        try:
            ltps, err = await run.io_bound(fetch_index_ltps, active)
            if market_utils.is_market_open():
                status_label.set_text("Status: monitoring " + " + ".join(active))
            else:
                status_label.set_text(f"Status: market closed (Mon\u2013Fri {config.MARKET_OPEN}\u2013{config.MARKET_CLOSE} IST)")

            for name in active:
                if not config.INDEXES[name]["enabled"]:
                    continue
                ltp = ltps.get(name)
                if ltp is None:
                    log(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {name} LTP unavailable ({err})")
                    continue
                p, mon = panels[name], monitors[name]
                p["ltp_label"].set_text(f"{name} LTP: {ltp}")

                try:
                    res = await run.io_bound(mon.step, client, ltp, None, datetime.now(market_utils.IST))
                    for msg in res["logs"]:
                        log(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                    if mon.strikes:
                        p["window_label"].set_text(f"Window: {min(mon.strikes)} - {max(mon.strikes)}")
                    if res["board_changed"] or res["recalculated"]:
                        p["render_board"]()
                    if res.get("first_updated"):
                        p["render_first"]()
                    if res.get("latest_updated"):
                        p["render_latest"]()
                    support_alerts = mon.pop_support_alerts()
                    if support_alerts:
                        notifier.dispatch_support_alerts(support_alerts, log_fn=log)
                    
                    await dispatch_orders(name)
                except Exception as ex:
                    log(f"[{datetime.now().strftime('%H:%M:%S')}] {name} BEP monitor error: {ex}")
            await refresh_order_tracking()
        finally:
            polling["busy"] = False

    async def dispatch_orders(name):
        """Sends every queued order signal of this index right away and records the result."""
        mon, p = monitors[name], panels[name]
        for sig in mon.pop_order_signals():
            res = await run.io_bound(order_bridge.send_order, sig)
            mon.record_order_result(sig, res["status"])
            log(f"[{datetime.now().strftime('%H:%M:%S')}] {res['message']}")
            add_order_row(sig, res)
            ui.notify(res["message"][:160], type={"sent": "positive", "dry_run": "info"}.get(res["status"], "negative"),
                      position="top", timeout=15000)
        p["render_locks"]()

    opening = {"busy": False}

    async def opening_loop():
        """Runs every OPENING_TICK_SECONDS. Prep window (OPENING_PREP_START-09:15): read NIFTY's pre-open price and
        prepare the strikes/BEPs. 09:15:00-09:20: check only the prepared strikes and send at once."""
        if not token_connected or opening["busy"]:
            return
        now = datetime.now(market_utils.IST)
        h, m = (int(x) for x in config.OPENING_PREP_START.split(":"))
        start, first, end = now.replace(hour=h, minute=m, second=0, microsecond=0), \
            now.replace(hour=9, minute=15, second=0, microsecond=0), now.replace(hour=9, minute=20, second=0, microsecond=0)
        if not (start <= now < end) or not market_utils.is_trading_day(now):
            return
        opening["busy"] = True
        try:
            for name in [n for n in config.INDEXES if config.INDEXES[n]["enabled"]]:
                mon, msgs = monitors[name], []
                try:
                    if now < first:
                        ltps, err = await run.io_bound(fetch_index_ltps, [name])
                        if ltps.get(name) is not None:
                            await run.io_bound(mon.prepare_opening, client, ltps[name], now, msgs.append)
                    else:
                        await run.io_bound(mon.opening_tick, client, now, msgs.append)
                except Exception as ex:
                    msgs.append(f"{name} opening order error: {ex}")
                stamp = datetime.now().strftime("%H:%M:%S")
                for msg in msgs:
                    log(f"[{stamp}] {msg}")
                await dispatch_orders(name)
        finally:
            opening["busy"] = False

    async def refresh_order_tracking():
        """Entry / Exit / LTP / Captured Points / P&L for SENT and DRY RUN rows in the orders table."""
        if not any(r.get("status") in trade_tracker.TRACKED for r in order_log):
            return
        trades, t_err = None, None
        now_ts = datetime.now().timestamp()
        has_sent = any(r.get("status") == "SENT" for r in order_log)
        if has_sent and now_ts - polling["trades_at"] >= config.TRADES_REFRESH_SECONDS:
            trades, t_err = await run.io_bound(client.fetch_trades_for_day)
            polling["trades_at"] = now_ts
            if trades is None:
                log(f"[{datetime.now().strftime('%H:%M:%S')}] Upstox trade book unavailable ({t_err}); Entry/Exit not updated.")
        expiries = {n: monitors[n].expiry for n in monitors}
        try:
            updates, err = await run.io_bound(trade_tracker.compute, client, order_log, expiries, trades)
        except Exception as ex:
            log(f"[{datetime.now().strftime('%H:%M:%S')}] Order tracking error: {ex}")
            return
        if not updates:
            return
        for r in order_log:
            if r["id"] in updates:
                r.update(updates[r["id"]])
        orders_table.rows = list(reversed(order_log))
        orders_table.update()

    scan_timer = ui.timer(config.SCAN_INTERVAL_SECONDS, poll)
    ui.timer(config.OPENING_TICK_SECONDS, opening_loop)


ui.run(title="BEP Support Monitor", port=8083, reload=False)