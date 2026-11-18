"""
app.py - NiceGUI screens for the BEP Support monitor (single-page app).

Layout: a fixed header (NIFTY LTP, status, connection, Dry run / LIVE, Pause buttons, theme) and a left navigation
drawer with six pages served by ui.sub_pages (no full page reloads):
  Dashboard . BEP Support . Common Price Watch . Orders . Setup (once a day) . Logs
All trading logic runs once in the background engine (engine.py); pages only read its state and redraw when the
matching version number changes.
"""
import json
from datetime import datetime

from nicegui import app, ui

import config
import export_utils
import order_bridge
from common_watch import CommonWatch
from engine import engine

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
    {"name": "pnl", "label": "P&L ₹", "field": "pnl", "align": "left"},
    {"name": "status", "label": "Status", "field": "status", "align": "left"},
    {"name": "detail", "label": "Detail", "field": "detail", "align": "left"},
]
ORDER_EXPORT_COLUMNS = [(c["name"], c["label"]) for c in ORDER_COLUMNS] + [("payload", "JSON")]
BEP_EXPORT_COLUMNS = [
    ("index", "Index"), ("opt", "Type"), ("strike", "Strike"), ("first", "First of day"),
    ("bep", "BEP"), ("time", "Support time"), ("setup", "Setup"), ("fail_level", "Fail level"),
    ("status", "Status"), ("fail_time", "Failed at"), ("fail_close", "Fail close"), ("ltp", "LTP"),
]
SUPPORT_GREEN = ("rgb(200,230,201)", "#1b3d1e")
SUPPORT_RED = ("rgb(255,205,210)", "#7f1d1d")

NAV = [
    ("/", "space_dashboard", "Dashboard"),
    ("/support", "stacked_line_chart", "BEP Support"),
    ("/watch", "visibility", "Common Price Watch"),
    ("/orders", "receipt_long", "Orders"),
    ("/setup", "tune", "Setup"),
    ("/logs", "article", "Logs"),
]

CSS = """
<style>
  body.body--dark { background: #0b1220; }
  .body--dark .q-drawer { background: #0f172a; }
  .body--dark .q-card { background: #111a2e; border: 1px solid #1e293b; }
  .body--dark .q-table__card { background: #111a2e; }
  .q-card { border-radius: 12px; }
  .nav-item { border-radius: 8px; margin: 2px 8px; }
  .nav-active { background: rgba(59,130,246,.18); color: #60a5fa; font-weight: 600; }
  .stat-label { font-size: 12px; opacity: .65; text-transform: uppercase; letter-spacing: .04em; }
  .stat-value { font-size: 22px; font-weight: 700; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
</style>
"""


def when_changed(keys, fn, interval: float = 1.0):
    """Calls fn() now and again whenever one of the engine's version counters in `keys` changes."""
    last = {"v": None}

    def tick():
        v = tuple(engine.versions[k] for k in keys)
        if v != last["v"]:
            last["v"] = v
            fn()
    ui.timer(interval, tick)


def card_title(text, icon=None):
    with ui.row().classes("items-center gap-2"):
        if icon:
            ui.icon(icon).classes("text-xl text-blue-5")
        ui.label(text).classes("text-md font-bold")


# ====================================================================== shell: header + navigation
@ui.page("/")
@ui.page("/{_:path}")
def root():
    ui.add_head_html(CSS)
    dark = ui.dark_mode(True)
    ui.colors(primary="#3b82f6")
    ui.run_javascript('if (Notification.permission === "default") { Notification.requestPermission(); }')
    nav_items = {}

    def set_active(path):
        for p, item in nav_items.items():
            item.classes(remove="nav-active")
            if p == path:
                item.classes(add="nav-active")

    with ui.header().classes("items-center gap-3 px-4 py-2 bg-[#0f172a] text-white border-b border-slate-800"):
        ui.button(icon="menu", on_click=lambda: drawer.toggle()).props("flat round color=white dense")
        ui.label("BEP AlgoDelta").classes("text-lg font-bold tracking-wide")
        ltp_lbl = ui.label("").classes("text-sm bg-slate-800 rounded px-2 py-1")
        status_lbl = ui.label("").classes("text-sm opacity-80")
        ui.space()
        conn_badge = ui.badge("").props("rounded")
        mode_badge = ui.badge("").props("rounded")
        alerts_badge = ui.badge("ALERTS PAUSED").props("rounded color=red")
        alert_btn = ui.button("", on_click=engine.toggle_alerts).props("dense no-caps")
        algo_btn = ui.button("", on_click=engine.toggle_algo_pause).props("dense no-caps")
        ui.button(icon="dark_mode", on_click=lambda: dark.toggle()).props("flat round color=white dense") \
            .tooltip("Light / dark")

    def refresh_header():
        parts = [f"{n} {engine.ltp[n]}" if engine.ltp[n] is not None else f"{n} --" for n in engine.active()]
        ltp_lbl.set_text(" · ".join(parts) or "--")
        status_lbl.set_text(engine.status)
        conn_badge.set_text("UPSTOX ✓ " + engine.user_name if engine.connected else "UPSTOX ✗")
        conn_badge.props("color=" + ("green-8" if engine.connected else "grey-7"))
        if config.AUTO_ORDER_PAUSED:
            mode_badge.set_text("ALGO PAUSED")
            mode_badge.props("color=grey-7")
        else:
            mode_badge.set_text("DRY RUN" if config.AUTO_ORDER_DRY_RUN else "LIVE")
            mode_badge.props("color=" + ("orange-8" if config.AUTO_ORDER_DRY_RUN else "red"))
        alerts_badge.set_visibility(config.ALERTS_PAUSED)
        alert_btn.set_text("Resume alerts" if config.ALERTS_PAUSED else "Pause alerts")
        alert_btn.props("icon=" + ("notifications_active color=green" if config.ALERTS_PAUSED
                                   else "notifications_off color=primary"))
        algo_btn.set_text("Resume algo" if config.AUTO_ORDER_PAUSED else "Pause algo")
        algo_btn.props("icon=" + ("play_arrow color=green" if config.AUTO_ORDER_PAUSED else "pause color=orange-8"))

    ui.timer(1.0, refresh_header)

    with ui.left_drawer(value=True, bordered=True).props("width=230").classes("pt-4") as drawer:
        for path, icon, label in NAV:
            with ui.item(on_click=lambda p=path: ui.navigate.to(p)).classes("nav-item cursor-pointer") as item:
                with ui.item_section().props("avatar"):
                    ui.icon(icon)
                with ui.item_section():
                    ui.label(label)
            nav_items[path] = item
        ui.separator().classes("my-3")
        ui.label("Setup is needed once a day; it is saved for the next start.").classes("text-xs opacity-60 px-4")

    # alerts: every open tab shows each new engine event once (toast + browser notification)
    seen = {"seq": engine.event_seq}

    def pump_events():
        for seq, e in engine.events:
            if seq <= seen["seq"]:
                continue
            seen["seq"] = seq
            ui.notify(e["msg"], type=e["type"], position="top", timeout=12000, multi_line=True)
            if e.get("title"):
                ui.run_javascript(f'if (Notification.permission === "granted") '
                                  f'{{ new Notification({json.dumps(e["title"])}, {{ body: {json.dumps(e["msg"])} }}); }}')

    ui.timer(0.5, pump_events)

    def page(path, builder):
        def build():
            set_active(path)
            with ui.column().classes("w-full p-4 gap-4"):
                builder()
        return build

    ui.sub_pages({path: page(path, b) for path, b in (
        ("/", dashboard_page), ("/support", support_page), ("/watch", watch_page),
        ("/orders", orders_page), ("/setup", setup_page), ("/logs", logs_page))})


# ====================================================================== Dashboard
def dashboard_page():
    ui.label("Dashboard").classes("text-2xl font-bold")
    if not engine.connected:
        with ui.card().classes("w-full bg-orange-1"):
            with ui.row().classes("items-center gap-3"):
                ui.icon("warning").classes("text-2xl text-orange-8")
                ui.label("Not connected to Upstox. Open Setup to enter today's token and upload the BEP CSV.") \
                    .classes("text-orange-10")
                ui.button("Go to Setup", on_click=lambda: ui.navigate.to("/setup")).props("dense")

    with ui.row().classes("w-full gap-4"):
        stats = {}
        for key, label in (("ltp", "NIFTY LTP"), ("window", "Strike window"), ("pnl", "Today P&L ₹"),
                           ("points", "Captured points"), ("orders", "Orders today")):
            with ui.card().classes("flex-1 min-w-[170px]"):
                ui.label(label).classes("stat-label")
                stats[key] = ui.label("--").classes("stat-value whitespace-nowrap")
                stats[key + "_sub"] = ui.label("").classes("text-xs opacity-60")

    def refresh_stats():
        name = engine.active()[0] if engine.active() else None
        mon = engine.monitors[name] if name else None
        stats["ltp"].set_text(str(engine.ltp.get(name)) if name and engine.ltp.get(name) is not None else "--")
        stats["window"].set_text(f"{min(mon.strikes)}–{max(mon.strikes)}" if mon and mon.strikes else "--")
        s = engine.pnl_summary()
        stats["pnl"].set_text(f"{s['pnl']:,.2f}")
        stats["pnl"].classes(remove="text-green-6 text-red-6")
        stats["pnl"].classes(add="text-green-6" if s["pnl"] >= 0 else "text-red-6")
        stats["points"].set_text(f"{s['points']:+.2f}")
        stats["points_sub"].set_text(f"{s['wins']} of {s['closed']} closed trades won")
        stats["window_sub"].set_text(f"{len(mon.strikes)} strikes" if mon and mon.strikes else "")
        stats["orders"].set_text(str(s["orders"]))

    ui.timer(1.0, refresh_stats)

    for name in engine.active():
        mon = engine.monitors[name]
        with ui.card().classes("w-full"):
            card_title(f"{name} — 09:15 opening order", "alarm")
            plan_lbl = ui.label("").classes("text-sm")
            lock_lbl = ui.label("").classes("text-sm font-medium text-blue-5")

            def refresh_plan(mon=mon, plan_lbl=plan_lbl, lock_lbl=lock_lbl):
                plan_lbl.set_text(mon.plan_text())
                lock_lbl.set_text(mon.side_status_text())
            ui.timer(2.0, refresh_plan)

        cards = {}
        with ui.row().classes("w-full gap-4"):
            for key, title, colour in (("first_CE", "First CE", "green"), ("first_PE", "First PE", "red"),
                                       ("latest_CE", "Latest Support CE", "green"),
                                       ("latest_PE", "Latest Support PE", "red")):
                with ui.card().classes("flex-1 min-w-[220px]") as c:
                    with ui.row().classes("items-center justify-between w-full no-wrap"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.icon("circle", color=colour).classes("text-xl")
                            ui.label(title).classes("stat-label")
                        badge = ui.badge("--").props("color=grey")
                    nm = ui.label("--").classes("text-xl font-bold")
                    det = ui.label("").classes("text-sm opacity-70")
                cards[key] = {"card": c, "badge": badge, "name": nm, "detail": det}

        def fill(w, kind, leg, state_colours, name=name):
            w["card"].classes(remove="bg-green-10 bg-red-10")
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
            if state_colours is not None and leg.get("state") == "red":
                w["card"].classes(add="bg-red-10")

        def refresh_cards(mon=mon, cards=cards, fill=fill):
            for kind in ("CE", "PE"):
                fill(cards[f"first_{kind}"], kind, (mon.first_view or {}).get(kind), None)
                fill(cards[f"latest_{kind}"], kind, (mon.latest_view or {}).get(kind), True)

        when_changed(["cards"], refresh_cards)

    with ui.card().classes("w-full"):
        card_title("Recent activity", "history")
        recent = ui.column().classes("w-full gap-0 mono text-xs")

        def refresh_recent():
            recent.clear()
            with recent:
                for line in engine.log_lines[-12:][::-1]:
                    ui.label(line).classes("whitespace-pre-wrap")
        when_changed(["log"], refresh_recent, 2.0)


# ====================================================================== BEP Support
def support_page():
    with ui.row().classes("w-full items-center justify-between"):
        ui.label("BEP Support").classes("text-2xl font-bold")

        def download_bep_xlsx():
            rows = []
            for n in engine.active():
                rows.extend(engine.monitors[n].export_rows())
            if not rows:
                ui.notify("No BEP Support rows to export yet", type="warning")
                return
            ui.download(export_utils.build_xlsx(rows, BEP_EXPORT_COLUMNS),
                        f"bep_support_{datetime.now().strftime('%Y-%m-%d')}.xlsx")
        ui.button("Download XLSX", icon="download", on_click=download_bep_xlsx).props("dense")
    ui.label("Green = a green candle touched BEP (low <= BEP) and closed above it. Red = one of the next 3 candles (15 min) "
             "closed below the fail level. ⭐ = first support of the day for that strike (alerts, and is added to the "
             "Common Price Watch when inside the ATM window).").classes("text-xs opacity-70")

    for name in engine.active():
        mon = engine.monitors[name]
        tables = {}
        with ui.row().classes("w-full no-wrap items-start gap-4"):
            for opt in ("CE", "PE"):
                with ui.card().classes("flex-1 min-w-0"):
                    card_title(f"{name} — {opt}", "trending_up" if opt == "CE" else "trending_down")
                    t = ui.table(columns=BOARD_COLUMNS, rows=[], row_key="id").classes("w-full") \
                        .props("dense flat").style("max-height: 70vh; overflow-y: auto")
                    t.add_slot("body", """
                        <q-tr :props="props" :style="props.row.bg ? {backgroundColor: props.row.bg, color: props.row.fg} : {}">
                          <q-td key="strike" :props="props"><span class="text-weight-bold">{{ props.row.strike }}</span><span v-if="props.row.first" style="margin-left:6px">⭐<q-tooltip>First support of the day for this strike</q-tooltip></span></q-td>
                          <q-td key="ltp" :props="props">{{ props.row.ltp }}</q-td>
                          <q-td key="bep" :props="props">{{ props.row.bep }}</q-td>
                          <q-td key="time" :props="props">{{ props.row.time }}</q-td>
                        </q-tr>""")
                    tables[opt] = t

        def render(mon=mon, tables=tables):
            view = mon.board_view()
            for opt, table in tables.items():
                rows = []
                for r in view.get(opt, []):
                    row = dict(r)
                    row["bg"], row["fg"] = SUPPORT_GREEN if r["kind"] == "green" else SUPPORT_RED
                    rows.append(row)
                table.rows = rows
                table.update()
        when_changed(["board"], render)


# ====================================================================== Common Price Watch
def watch_page():
    ui.label("Common Price Watch").classes("text-2xl font-bold")
    ui.label("Manual rows alert when a leg's candle closes ABOVE the common price (crossing up from at or below); red = "
             "closed back below after triggering. ⭐ rows are added automatically for a live first support of the day "
             "inside the ATM window (Level = BEP); red when the board row turns red. Nothing is placed automatically: "
             "use Place order.").classes("text-xs opacity-70")
    for name in engine.active():
        mon, cw = engine.monitors[name], engine.watches[name]
        with ui.card().classes("w-full"):
            card_title(f"{name} — add a strike", "add_circle")
            with ui.row().classes("items-end gap-6"):
                cw_strike = ui.number("Strike", value=(mon.strikes[len(mon.strikes) // 2] if mon.strikes else None),
                                      step=config.INDEXES[name]["strike_interval"], precision=0).classes("w-32")
                with ui.column().classes("gap-0"):
                    ui.label("Leg").classes("text-xs opacity-70")
                    cw_leg = ui.radio(["Both", "CE", "PE"], value="Both").props("inline dense")
                cw_price = ui.number("Common price", value=None, min=0, step=0.05).classes("w-36")
                with ui.column().classes("gap-0"):
                    ui.label("Timeframe").classes("text-xs opacity-70")
                    cw_tf = ui.radio({3: "3 min", 5: "5 min"}, value=5).props("inline dense")

                def add_watch(name=name, cw_strike=cw_strike, cw_leg=cw_leg, cw_price=cw_price, cw_tf=cw_tf):
                    step = config.INDEXES[name]["strike_interval"]
                    try:
                        strike, price = int(cw_strike.value), float(cw_price.value)
                    except (TypeError, ValueError):
                        ui.notify("Enter a strike and a common price.", type="negative")
                        return
                    if strike <= 0 or strike % step or price <= 0:
                        ui.notify(f"Strike must be a multiple of {step}; common price above 0.", type="negative")
                        return
                    engine.add_watch(name, strike, cw_leg.value, price, int(cw_tf.value))
                    ui.notify(f"Watching {strike} {cw_leg.value} at {price:g} ({cw_tf.value} min).", type="positive")
                ui.button("Add", icon="add", on_click=add_watch)

        with ui.card().classes("w-full"):
            card_title(f"{name} — watched strikes", "visibility")
            holder = ui.column().classes("w-full")

            async def place(row_id, name=name):
                await engine.place_watch_order(name, row_id)

            def render(cw=cw, holder=holder, place=place, name=name):
                holder.clear()
                with holder:
                    if not cw.rows:
                        ui.label("No strikes watched yet.").classes("text-sm opacity-70")
                        return
                    with ui.grid(columns="90px 80px 50px 100px 60px 140px 1fr 230px") \
                            .classes("w-full items-center gap-x-3 gap-y-1"):
                        for head in ("Source", "Strike", "Type", "Level", "TF", "Last close", "Status", ""):
                            ui.label(head).classes("stat-label")
                        for r in cw.rows:
                            bg = {"triggered": "bg-green-10 text-green-2", "failed": "bg-red-10 text-red-2"}.get(r["status"], "")
                            src = f"⭐ {r['trig_time']}" if r.get("source") == "star" else "Manual"
                            cells = [src, str(r["strike"]), r["opt"], f"{r['price']:g}", f"{r['tf']} min",
                                     (f"{r['last_close']:.2f} ({r['last_time']})" if r["last_close"] is not None else "--"),
                                     CommonWatch.status_text(r)]
                            for txt in cells:
                                ui.label(txt).classes(f"text-sm px-2 py-1 rounded {bg}")
                            with ui.row().classes("gap-1 no-wrap"):
                                done = r["order_status"] in ("SENT", "DRY RUN", "sending")
                                b = ui.button(f"Ordered ({r['order_status']})" if done else "Place order",
                                              on_click=lambda _e, i=r["id"]: place(i)).props("dense size=sm color=green")
                                b.set_enabled(r["status"] == "triggered" and not done)
                                ui.button(icon="delete", on_click=lambda _e, i=r["id"]: engine.remove_watch(name, i)) \
                                    .props("dense flat size=sm color=grey-6")
            when_changed(["watch"], render)


# ====================================================================== Orders
def orders_page():
    with ui.row().classes("w-full items-center justify-between"):
        ui.label("AlgoDelta orders").classes("text-2xl font-bold")
        with ui.row().classes("gap-2"):
            ui.button("CSV", icon="download", on_click=lambda: ui.download(
                export_utils.build_csv(list(engine.order_log), ORDER_EXPORT_COLUMNS),
                f"algodelta_orders_{datetime.now().strftime('%Y-%m-%d')}.csv")).props("dense outline")
            ui.button("XLSX", icon="download", on_click=lambda: ui.download(
                export_utils.build_xlsx(list(engine.order_log), ORDER_EXPORT_COLUMNS),
                f"algodelta_orders_{datetime.now().strftime('%Y-%m-%d')}.xlsx")).props("dense outline")
    summary = ui.label("").classes("text-sm")
    with ui.card().classes("w-full"):
        table = ui.table(columns=ORDER_COLUMNS, rows=[], row_key="id").classes("w-full").props("dense flat")
        table.add_slot("body-cell-status", '''
            <q-td key="status" :props="props">
                <q-badge :color="props.value === 'SENT' ? 'green' : props.value === 'DRY RUN' ? 'blue' : props.value === 'FAILED' ? 'red' : 'orange'">{{ props.value }}</q-badge>
            </q-td>''')
        for col in ("points", "pnl"):
            table.add_slot(f"body-cell-{col}", f'''
            <q-td key="{col}" :props="props" :class="typeof props.value === 'number' ? (props.value >= 0 ? 'text-green-6 text-weight-bold' : 'text-red-6 text-weight-bold') : ''">{{{{ props.value }}}}</q-td>''')
        table.add_slot("body-cell-detail", '''
            <q-td key="detail" :props="props" style="max-width: 260px; white-space: normal; word-break: break-word">{{ props.value }}</q-td>''')
    ui.label("Entry / Exit of SENT orders are the real fills from today's Upstox trade book (refreshed every "
             f"{config.TRADES_REFRESH_SECONDS} s). Captured Points = Exit − Entry, shown once the trade has exited. "
             "DRY RUN rows have no exit.").classes("text-xs opacity-70")

    def render():
        table.rows = list(reversed(engine.order_log))
        table.update()
        s = engine.pnl_summary()
        summary.set_text(f"{s['orders']} orders · {s['closed']} closed · {s['wins']} won · "
                         f"points {s['points']:+.2f} · P&L ₹{s['pnl']:,.2f}")
    when_changed(["orders"], render)


# ====================================================================== Setup (once a day)
def setup_page():
    ui.label("Setup").classes("text-2xl font-bold")
    ui.label("Needed once a day. Everything except the Upstox token is saved and comes back after a restart; "
             "the app always starts in Dry run.").classes("text-xs opacity-70")

    with ui.row().classes("w-full gap-4 items-stretch"):
        # ---- Upstox
        with ui.card().classes("flex-1 min-w-[320px]"):
            card_title("Upstox", "key")
            token = ui.input("Upstox access token", password=True, password_toggle_button=True).classes("w-full")
            conn = ui.label(engine.connection_text).classes("text-sm")

            async def connect():
                conn.set_text("Testing...")
                ok, text = await engine.connect(token.value)
                conn.set_text(text)
                ui.notify(text, type="positive" if ok else "negative")
            ui.button("Save & test connection", icon="link", on_click=connect).classes("w-full")

        # ---- BEP files
        with ui.card().classes("flex-1 min-w-[320px]"):
            card_title("BEP files", "upload_file")
            import bep as _bep
            uploaders = {}
            for name in config.INDEXES:
                status = ui.label(_bep.status_text(name)).classes("text-sm opacity-80")
                result = ui.label(engine.bep_upload_text[name]).classes("text-sm")

                async def on_upload(e, name=name, status=status, result=result):
                    if hasattr(e, "file"):
                        data, fname = await e.file.read(), getattr(e.file, "name", "")
                    else:
                        data, fname = e.content.read(), getattr(e, "name", "")
                    engine.upload_bep(name, data, fname)
                    result.set_text(engine.bep_upload_text[name])
                    status.set_text(_bep.status_text(name))
                    try:
                        uploaders[name].reset()
                    except Exception:
                        pass
                up = uploaders[name] = ui.upload(on_upload=on_upload, auto_upload=True, max_files=1).props("accept=.csv").classes("hidden")
                ui.button(f"Upload {name} BEP CSV", icon="upload", on_click=lambda u=up: u.run_method("pickFiles")) \
                    .classes("w-full")

        # ---- Scanner
        with ui.card().classes("flex-1 min-w-[320px]"):
            card_title("Scanner", "radar")
            total = 2 * config.STRIKES_EACH_SIDE + 1
            slider = ui.slider(min=1, max=11, step=2, value=total).classes("w-full")
            ui.label().bind_text_from(slider, "value", lambda v: f"{int(v)} strikes (centre ± {(int(v) - 1) // 2})") \
                .classes("text-sm")
            ui.button("Save strike count", on_click=lambda: (engine.set_strike_count(int(slider.value)),
                                                             ui.notify("Strike count saved", type="positive"))) \
                .classes("w-full")
            interval = ui.number("Scan interval (seconds)", value=config.SCAN_INTERVAL_SECONDS, min=1, step=1,
                                 precision=0).classes("w-full")

            def save_interval():
                if not interval.value or int(interval.value) < 1:
                    ui.notify("Scan interval must be at least 1 second.", type="negative")
                    return
                engine.set_scan_interval(int(interval.value))
                ui.notify("Scan interval saved", type="positive")
            ui.button("Save scan interval", on_click=save_interval).classes("w-full")
            ui.button("Rescan from 09:15", icon="restart_alt", on_click=lambda: (engine.rescan(),
                                                                                ui.notify("Rescanning from 09:15"))) \
                .props("color=orange-8").classes("w-full")

        # ---- Trading controls
        with ui.card().classes("flex-1 min-w-[320px]"):
            card_title("Trading", "shield")
            dry = ui.switch("Dry run (only log the JSON, send nothing)", value=config.AUTO_ORDER_DRY_RUN)

            def on_dry(ev):
                if ev.value:
                    engine.set_dry_run(True)
                    return
                with ui.dialog() as dlg, ui.card():
                    ui.label("Turn OFF dry run? Orders will be sent to AlgoDelta and placed with real money.")
                    with ui.row():
                        ui.button("Cancel", on_click=dlg.close)
                        ui.button("Yes, go live", on_click=lambda: (engine.set_dry_run(False), dlg.close())) \
                            .props("color=red")
                dlg.on("hide", lambda: dry.set_value(config.AUTO_ORDER_DRY_RUN))
                dlg.open()
            dry.on_value_change(on_dry)
            ui.number("Max orders/day", value=config.AUTO_ORDER_DAILY_LIMIT, min=1, precision=0, step=1,
                      on_change=lambda ev: engine.set_daily_limit(int(ev.value or 1))).classes("w-full")
            ui.label("Pause alerts / Pause algo are in the header.").classes("text-xs opacity-70")

    for name in config.INDEXES:
        algodelta_card(name)


def algodelta_card(name):
    ad_cfg = config.AUTO_ORDER[name]
    with ui.card().classes("w-full"):
        card_title(f"{name} — AlgoDelta order settings", "send")
        with ui.row().classes("w-full gap-6 items-start"):
            with ui.column().classes("flex-1 min-w-[320px] gap-2"):
                ad_url = ui.input("Webhook URL (AlgoDelta: Copy Webhook)", value=ad_cfg["webhook_url"],
                                  password=True, password_toggle_button=True).classes("w-full")
                with ui.row().classes("items-center gap-2"):
                    ui.button("JSON template", icon="edit", on_click=lambda: tpl_dialog.open()) \
                        .props("flat dense no-caps color=primary").classes("underline")
                    tpl_tag = ui.badge("default").props("outline color=grey-6")
                ad_qty = ui.number("Quantity (lots)", value=ad_cfg["qty"], min=1, precision=0, step=1).classes("w-full")
                with ui.row().classes("w-full gap-2 no-wrap"):
                    ad_tgt_type = ui.select(["POINT", "LTP"], value=ad_cfg.get("tgt_type", "POINT"), label="Target type").classes("flex-1")
                    ad_tgt = ui.number("Target value", value=ad_cfg["tgt"], min=0, step=1).classes("flex-1")
                with ui.row().classes("w-full gap-2 no-wrap"):
                    ad_sl_type = ui.select(["POINT", "LTP"], value=ad_cfg.get("sl_type", "POINT"), label="Stop loss type").classes("flex-1")
                    ad_sl = ui.number("Stop loss value", value=ad_cfg["sl"], min=0, step=1).classes("flex-1")
            with ui.column().classes("flex-1 min-w-[320px] gap-2"):
                ad_max_above = ui.number("09:15 order: max points above BEP (skip at or above)",
                                         value=ad_cfg.get("max_above_bep", 15), min=0, step=1).classes("w-full")
                ad_exit_opp = ui.switch("Exit on opposite signal", value=ad_cfg.get("exit_on_opposite", False))
                ad_trail = ui.switch("Trailing SL", value=ad_cfg.get("trail", False))
                with ui.row().classes("w-full gap-2 no-wrap"):
                    ad_trail_type = ui.select(["POINT", "LTP"], value=ad_cfg.get("trail_type", "LTP"), label="Trail type").classes("flex-1")
                    ad_trail_trigger = ui.number("Trigger", value=ad_cfg.get("trail_trigger", 20), min=0, step=1).classes("flex-1")
                    ad_trail_point = ui.number("Point", value=ad_cfg.get("trail_point", 1), min=0, step=1).classes("flex-1")
                    ad_trail_gap = ui.number("Gap", value=ad_cfg.get("trail_gap", 20), min=0, step=1).classes("flex-1")
                for w in (ad_trail_type, ad_trail_trigger, ad_trail_point, ad_trail_gap):
                    w.bind_enabled_from(ad_trail, "value")
                ad_confirm = ui.checkbox("I checked this JSON against the Syntax Generator", value=ad_cfg["confirmed"])
        ad_status = ui.label("").classes("text-sm")
        with ui.row().classes("gap-2"):
            ui.button("Save", icon="save", on_click=lambda: save())
            ui.button("Preview JSON", on_click=lambda: preview()).props("outline")

    with ui.dialog() as tpl_dialog, ui.card().style("width: 720px; max-width: 95vw"):
        ui.label(f"{name} — JSON template (strategy_order)").classes("text-lg font-bold")
        ad_template = ui.textarea(value=json.dumps(ad_cfg["templates"]["strategy_order"], indent=2)) \
            .classes("w-full mono").props("outlined input-style='font-family: monospace; font-size: 12px' rows=18")
        ui.label("Placeholders: {symbol} {opt} {signal} {qty} {tgt} {tgt_type} {sl} {sl_type} {strike} {expiry} {index} "
                 "{bep} {ltp} {exit_on_opposite} {is_trail} {trail_type} {trail_trigger} {trail_point} {trail_gap}. "
                 "{symbol} = index + expiry + strike + CE/PE, e.g. NIFTY17NOV2625400CE. {signal} = UP for CE, DOWN for PE. "
                 "exit_on_opposite, is_trail_set and the trail_* keys are always set from the controls.").classes("text-xs opacity-70")
        tpl_status = ui.label("").classes("text-sm")

        def reset_template():
            ad_template.set_value(json.dumps(config._STRATEGY_ORDER, indent=2))
            tpl_status.set_text("Reset to the default template (not saved yet; click Save).")
        with ui.row().classes("w-full gap-2 justify-end"):
            ui.button("Reset to default", icon="restart_alt", on_click=reset_template).props("flat color=orange")
            ui.button("Preview JSON", on_click=lambda: preview()).props("outline")
            ui.button("Save", on_click=lambda: (save(), tpl_status.set_text(ad_status.text)))
            ui.button("Close", on_click=tpl_dialog.close).props("flat")

    def update_tag():
        try:
            cur = json.loads(ad_template.value)
        except ValueError:
            cur = None
        text = "default" if cur == config._STRATEGY_ORDER else "edited"
        if cur != ad_cfg["templates"]["strategy_order"]:
            text += " · not saved"
        tpl_tag.set_text(text)
        tpl_tag.props("outline color=" + ("grey-6" if text == "default" else "orange"))
    update_tag()
    ad_template.on_value_change(lambda ev: (update_tag(), ad_confirm.set_value(False)))

    def parse_template():
        try:
            obj = json.loads(ad_template.value)
        except ValueError as ex:
            return None, f"JSON error: {ex}"
        if not isinstance(obj, dict):
            return None, "The template must be one JSON object { ... }."
        if obj.get("type") != "strategy_order":
            return None, f"\"type\" must be \"strategy_order\" (found {obj.get('type')!r})."
        return obj, ""

    def numbers():
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
                return None, "Trail Trigger, Point and Gap must be numbers above 0."
            if ad_trail_type.value == "POINT" and t_gap >= t_trig:
                return None, "With Trail type POINT, Gap must be smaller than Trigger."
        return {"tgt": tgt, "sl": sl, "qty": int(qty), "tgt_type": ad_tgt_type.value, "sl_type": ad_sl_type.value,
                "exit_on_opposite": bool(ad_exit_opp.value), "trail": trail, "max_above_bep": max_above,
                "trail_type": ad_trail_type.value,
                "trail_trigger": t_trig if t_trig is not None else ad_cfg.get("trail_trigger", 20),
                "trail_point": t_point if t_point is not None else ad_cfg.get("trail_point", 1),
                "trail_gap": t_gap if t_gap is not None else ad_cfg.get("trail_gap", 20)}, ""

    def save():
        obj, err = parse_template()
        if obj is None:
            ad_status.set_text("❌ " + err)
            return
        nums, err = numbers()
        if nums is None:
            ad_status.set_text("❌ " + err)
            return
        url = (ad_url.value or "").strip()
        if url and not url.lower().startswith("https://"):
            ad_status.set_text("❌ The webhook URL must start with https://")
            return
        saved = engine.save_auto_order(name, obj, nums, url, bool(ad_confirm.value))
        update_tag()
        trail_txt = (f"trail ON ({nums['trail_type']}: trigger {nums['trail_trigger']}, point {nums['trail_point']}, "
                     f"gap {nums['trail_gap']})" if nums["trail"] else "trail OFF")
        ad_status.set_text(f"✅ {saved} Target {nums['tgt']} ({nums['tgt_type']}), SL {nums['sl']} ({nums['sl_type']}), "
                           f"qty {nums['qty']}; {trail_txt}; exit on opposite {'ON' if nums['exit_on_opposite'] else 'OFF'}; "
                           f"09:15 order only if LTP is < {nums['max_above_bep']} above BEP; "
                           f"webhook {'set' if url else 'NOT set'}; JSON {'confirmed' if ad_confirm.value else 'NOT confirmed'} "
                           f"(live orders need both).")

    def preview():
        obj, err = parse_template()
        if obj is None:
            ad_status.set_text("❌ " + err)
            return
        nums, err = numbers()
        if nums is None:
            ad_status.set_text("❌ " + err)
            return
        sample = {"index": name, "opt": "CE", "strike": 25400, "expiry": "2026-11-17", "bep": 100.0, "ltp": 101.5}
        payload = order_bridge.build_payload(sample, obj, nums)
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Sample order JSON ({name} 25400 CE, expiry 17 Nov 2026)").classes("font-bold")
            ui.code(json.dumps(payload, indent=2), language="json")
            ui.button("Close", on_click=dlg.close)
        dlg.open()


# ====================================================================== Logs
def logs_page():
    with ui.row().classes("w-full items-center justify-between"):
        ui.label("Logs").classes("text-2xl font-bold")
        ui.button("Download", icon="download", on_click=lambda: ui.download(
            "\n".join(engine.log_lines).encode("utf-8"), f"bep_log_{datetime.now().strftime('%Y-%m-%d')}.txt")) \
            .props("dense outline")
    box = ui.log(max_lines=1000).classes("w-full mono text-xs").style("height: 75vh")
    shown = {"n": 0}

    def push():
        lines = engine.log_lines
        if shown["n"] > len(lines):                       # the engine trimmed old lines
            box.clear()
            shown["n"] = 0
        for line in lines[shown["n"]:]:
            box.push(line)
        shown["n"] = len(lines)
    when_changed(["log"], push)


# ====================================================================== background engine (once for the whole app)
engine.scan_timer = app.timer(config.SCAN_INTERVAL_SECONDS, engine.scan)
app.timer(config.OPENING_TICK_SECONDS, engine.opening)

ui.run(title="BEP AlgoDelta", port=8083, reload=False, dark=True)
