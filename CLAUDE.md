# CLAUDE.md: BEP AlgoDelta project context (read at the start of every session)

Repo: `ArunkumarEkambaram/BEP-AlgoDelta` (branch `main`, latest merge = PR #73 (09:15 BEP order switch + No trade today, decision 41); updated together with each feature PR).
Run: `python app.py` → http://localhost:8083. Needs `nicegui>=3.1.0`, Python 3.14 on the user's PC.
Related repos: `ArunkumarEkambaram/BEP_Upstox` (**the successor app**, built 24 Nov 2026: the same BEP logic with orders sent directly to Upstox; see "BEP Upstox" below), `ArunkumarEkambaram/LTP_Crossing` (reference only, do not change).
**This app stays the user's live app and the safety backup** until BEP Upstox is proven live (decision on Fri 11 Dec 2026).

## Working rules agreed with the user
- **Always discuss requirements before writing code.** Ask questions with "Suggested:" answers and wait for the user's go-ahead.
- Work on a branch, open a PR, and merge **only when the user says "merge PR #n"**. This applies to **every** change, docs-only ones included (no direct pushes to `main`; confirmed again after PR #17).
- During market hours, **don't push**. Keep work on a local branch until the user says so.
- **Never change `main` directly** (no commits, pushes or merges to it on Claude's own initiative), especially near or during market hours. Every change, docs-only ones included, goes to a **new branch**. It's merged later, only when the user says "merge PR #n". The user's running app stays on the `main` it pulled. (Asked on 20 Nov 2026, just before the open. The user can allow an exception in chat, as for PR #23.)
- After merging, the user runs `git pull origin main` and restarts the app.
- `__pycache__/`, `settings.json`, `upstox_token.json`, `orders_*.csv` and `common_watch_*.json` are git-ignored. Never commit them.
- The cloud session can't delete GitHub branches (proxy 403). The user deletes merged branches, or turns on "Automatically delete head branches".
- **New features and fixes go into BOTH projects** (BEP-AlgoDelta and BEP_Upstox) until one is retired (user, 24 Nov): one PR per repo, and remind the user to merge both. Examples: the NIFTY change % (PR #50 here, BEP_Upstox PR #6), max loss per day (PR #52 here, BEP_Upstox PR #7).

## Architecture (after PR #3)
- `engine.py`: **one background engine** for the whole app (`app.timer`). It handles the Upstox connection, scans, the 09:15 order, Order Management, orders, tracking, log and alerts. Pages only read its state; version counters trigger redraws, and events trigger toasts and browser notifications in every tab.
- `app.py`: NiceGUI **single-page app** (`ui.sub_pages`), dark theme with a toggle, a header (LTP, status, Upstox ✓, DRY RUN/LIVE, Pause alerts, Pause algo) and a left nav. The pages are:
  - **Dashboard**
  - **BEP Support**: a nav group (PR #33) with **Support board** (`/support/board`; `/support` opens it) and **BEP Pair cross** (`/support/pair-cross`, decision 25). Both pages have **Download XLSX** (two sheets) and the **Replay a past day** bar.
  - **Order Management**: a nav group with **four** sub-pages (three since decision 42: Pair and ⭐ merged into Pair & ⭐), each with its own Add form (⭐ has none, rows are added automatically) and list. They are `/order-management/same-strike`, `/order-management/pair`, `/order-management/bep-star` and `/order-management/manual-entry`; `/order-management` opens Same strike. Each sub-item shows a row count, and its badge is green when a row is triggered and waiting for Place order. Add a sub-page through `OM_SUB` in `app.py`. Each row is an **order card** (like AlgoDelta's): a header with symbol/Buy/INTRADAY/TF, a status chip (WAITING, TRIGGERED, PENDING, ORDERED · SENT/DRY RUN, SQUARING OFF, EXITED · reason, FAILED, plus the limit chips of decision 16) and ⚡ Place / ✕ Delete / ✏ Edit (WAITING only). The body shows Entry Price (**Entry (filled)** once ordered), Quantity (lots, editable per card until ordered), P&L (**open P&L while running**, decision 22), live LTP, the level box (**Common price / Pair price / BEP / Order type**, decision 19), Target, Stoploss and Trailing (per card, PR #15; editable as app rules while the order is open, decision 18). A "Compact view" switch brings back the table. Live option LTP comes from `engine.refresh_option_ltps` (one batched call every `OPTION_LTP_SECONDS` = 2 s). Each card is linked to its order through `order_id`, which supplies Entry and the realized P&L (open P&L is computed locally from the 2 s LTP). **Entry at a price (PR C):**
    - Entry Price on a card is editable until it's ordered. Empty means a market order at ⚡.
    - With a price, ⚡ (only once TRIGGERED, so no pre-arm) **arms** the card. The chip shows `PENDING @ 95.00 ↓`, the app checks the live LTP every 2 s, and when LTP is ≤ the price (↓ dip) or ≥ it (↑ breakout) it sends the normal market `strategy_order`.
    - The direction is set automatically from the LTP at arming, and the arrow flips it.
    - It cancels via the button, automatically when the card turns FAILED/EXITED, and at 15:15. Pause algo and the daily limit apply, inside `send_order`.
    - The signal LTP of a manual order (= dry-run Entry) is now the **live LTP at the click or the price hit**, not the candle close.
    - AlgoDelta's `strategy_order` has **no entry-price field** (checked by the user), so this app-side PENDING logic stays.
  - **Order Details**
  - **Setup**
  - **Logs**
- `bep_monitor.py`: BEP Support board, ⭐ first support, and the 09:15 opening order (prepare + 1 s tick).
- `pair_cross.py`: BEP Pair cross table (decision 25), run by `BepMonitor._cross_step` on the board's candles.
- `replay.py`: Replay a past day (a separate `BepMonitor` with `replay=True`, historical candles through `ReplayClient`).
- `common_watch.py`: Order Management rows (Same strike, Pair, ⭐, Manual Entry).
- `order_bridge.py`: AlgoDelta JSON: `strategy_order`, `limit_order`, `squareoff_position` and `cancel_order`.
- `limit_orders.py`: Manual Entry Limit mode helpers (state in the order row's `mg` column, app SL/Target/trail checks, Upstox order-book matching).
- `trade_tracker.py`: Order Details Entry/Exit/LTP/Points/P&L. Live orders use Upstox fills (FIFO per order); dry run is simulated.
- `exit_rules.py`: one evaluator for SL/Target rules on 1-min candles (LTP / POINT / CANDLE, trailing SL, 15:15 exit).
- `settings_store.py`: `settings.json` (Setup values) and `upstox_token.json` (today's token only).
- `config.py`: NIFTY only (lot size 65, strike step 50), defaults, and `OPENING_PREP_START = "09:08"`.

## Feature decisions (in order)
1. **Polling fix (PR #2):** the polling block was wrongly indented inside `build_panel()` after its `return`.
2. **NIFTY only**; SENSEX removed (re-add notes are in `config.py`). Port 8083.
3. **AlgoDelta JSON:** a template popup with a default/edited badge. Trailing SL (type LTP/POINT, trigger, point, gap) and Exit on opposite: both switches default OFF, and the controls always override the template.
4. **Trailing SL rule:** once the high reaches entry + trigger, SL = high − gap (in steps of point), and it never moves down. For example, entry 178, SL 166, trigger 20, gap 20: at 198 the SL goes to 178 (cost), and at 210 it's 190. Gap may equal Trigger.
5. **09:15 opening order (automatic):**
   - 09:08–09:15: read NIFTY's pre-open price and pick the strike just below and just above it (the same two for CE and PE), with their BEPs. The plan freezes at 09:15.
   - 09:15:00–09:20: every 1 s, one Upstox OHLC call. The rule: the first candle's low touched BEP, LTP is above the open and above BEP, and **LTP − BEP < 15** (editable).
   - **One CE and one PE per day.** If both strikes qualify, the one closest to the pre-open price wins. SENT, DRY RUN and FAILED lock the side; BLOCKED frees it. The lock is restored from today's orders file.
   - **No plan before 09:15** (late start or restart) means **no 09:15 order** that day.
   - Still unverified live: whether Upstox's NIFTY value between 09:08 and 09:15 equals the pre-open price. A manual override was offered if it doesn't.
   - **Entry at BEP + 2 and a CANDLE SL at BEP − 2 (PR #41, user request on 23 Nov):**
     - Entry: LTP ≥ **BEP + `open_entry_above`** (2) instead of LTP > BEP. The touch, LTP > open, one CE + one PE, `max_above_bep` (still from BEP) and the market `strategy_order` stay. With `open_entry_above` = 0 it's the old LTP > BEP.
     - SL: a **5-min candle close below BEP − `open_sl_below`** (2), e.g. BEP 150 → exit on a 5-min close below 148 (a wick doesn't exit). It's stored on the order as a CANDLE `c_sl` (`BepMonitor._opening_sl`) and the order is sent with `is_sl` false, so **AlgoDelta holds no SL**: the app squares off (keep the PC on). The Setup trailing SL, if on, is watched by the app too (`c_trail`). The Target stays the Setup Target, held by AlgoDelta.
     - Setup: "09:15 entry above BEP +" (2), "09:15 SL: close below BEP −" (2), "SL candle" 1 / 3 / 5 min (5) (`open_entry_above`, `open_sl_below`, `open_sl_tf` in `AUTO_ORDER`, saved in settings.json).
   - **Max SL 17 points, held by AlgoDelta (PR #47, user request 23 Nov):** the candle SL had no cap (a fall inside a 5-min candle exits only at the close) and nothing exited if the PC was off. Now the order is sent with `is_sl` true and a **POINT SL of `open_max_sl`** (17) from AlgoDelta's fill, e.g. BEP 150, entry 152 → max SL 135, and `is_trail_set` false (the Setup trail stays with the app, `c_trail`, so AlgoDelta's 135 stays fixed). The 5-min close below BEP − 2 stays the normal exit; whichever hits first exits. Near the top of the range (entry 165) both are 148, but the max SL fires on the LTP. Planned risk was 4 to ~17 points (entry BEP + 2 to < BEP + 15).
     - Setup "09:15 max SL: points below the fill (AlgoDelta, 0 = none)" (`open_max_sl`, saved; 0 = the old `is_sl` false). The Log line and Order Details SL / Target show "Max SL 17 pts (AlgoDelta)". Dry run simulates both rules (checked: drift → candle SL 147; crash to 130 inside a candle → 135).
     - No double exit: live, the app's candle rule is checked only while the Upstox trade book shows no exit (30 s refresh).
6. **Order Details:** Entry, Exit, LTP, Captured Points (**Exit − Entry** once exited; while open, `x (open)` from the live LTP, decision 22) and P&L ₹ (the same).
   - **Live:** Upstox trade book (`get-trades-for-day`, every 30 s). Fills are matched by option and **shared FIFO between orders on the same option** (PR #10).
   - **Dry run:** entry = LTP at the signal. The exit is **simulated** from 1-min candles using the order's SL/Target/trail (SL first if both hit in the same minute; 15:15 square-off). It's saved in the orders file.
   - The JSON column is hidden in the table but kept in the file and the CSV/XLSX downloads.
7. **Order Management** (manual trades: alert, then **Place order**; nothing automatic). Sections (now sub-pages; Manual Entry came later, decision 13):
   - **Same strike:** strike, Leg (Both/CE/PE), common price, timeframe **1/3/5 min**, Trigger on **Candle close / Live LTP**, Order **Strategy / Limit** (decisions 17, 20). Fires when an **armed** leg (it traded at or below the price after the add: close, wick or live LTP) closes above the price, or with Live LTP its LTP goes above it, **once**. A later close below turns the row red, with no alert. Rows added pre-open use the **first candle's open** as the previous price, so the earliest trigger is 09:20 / 09:18 (PR #10).
   - **Pair (CE vs PE):** CE strike, PE strike, common price (optional separate PE price), buffer (default 1).
     - **Entry, either side:** a leg closes above its price while the opponent closes below price − buffer (or, with Trigger on Live LTP, the same on the LTPs). The leg must have traded at or below its price first ("armed": a close, a wick or the live LTP, decision 20).
     - **Exit:** the order's SL/Target, **or** the opponent closing at or above price − buffer. Live, that sends `squareoff_position` automatically, and it isn't blocked by Pause algo or the daily limit. In dry run the exit is recorded.
   - **BEP Support ⭐:** a live first support inside the ATM window is added automatically and is ready to order (option A). It turns red when the board row fails. A 09:15 ⭐ is skipped if that side already has its opening order. Same-strike and ⭐ rows can coexist at different levels.
   - "Both" legs are independent rows (no change wanted).
8. **Targets per type (PR #8):** Setup holds default targets for Same strike, Pair and ⭐, and the 09:15 order uses the main Target. The SL and trailing SL are common.
9. **Per-order SL/Target (PR #9):** SL and Target switches open a popup with Type **LTP / POINT / CANDLE**, Time frame 1/3/5 min, and Value.
   - **CANDLE:** exit only when a candle **closes** below (SL) or above (Target) the value; a wick doesn't exit. Candles are aligned to 09:15.
   - **Before placing (Order Management):** LTP/POINT are sent to AlgoDelta. CANDLE is sent with `is_sl`/`is_tgt` false (no trail), and the app watches it and squares off.
   - **After placing (Order Details, not the 09:15 order):** the app watches the rule. AlgoDelta's original SL/Target stay active, because there's no modify syntax.
10. **UI (PR #3, plus tweaks):**
    - BEP Support rows are white, and only failed rows are red.
    - Pages are renamed: Order Management (formerly Common Price Watch) and Order Details (formerly Orders).
    - The log is full height.
    - Setup is saved, except that Dry run always starts ON.
    - The Upstox token is saved for **today only** and reconnects automatically on start; there's a "Forget saved token" button.
11. **Per-card Trailing SL (PR #15):**
   - Click the card's Trailing box to open a popup: ON/OFF, Type, Trigger, Point and Gap. It starts from Setup and is stored as `c_trail` (`engine.row_trail`).
   - It's sent in that card's JSON (and simulated in dry run) and locks once ordered. With a CANDLE SL (`is_sl` false), AlgoDelta can't trail, so since PR #24 **the app** watches the trail instead (decision 18).
   - Ordered cards show the Target, SL and Trail **as sent** (from the order JSON).
   - Start/End time was dropped (the user doesn't want it).
12. **Manual square-off (PR #16):**
   - **Where:** a **Square off** button on ordered cards (Order Management) and in the Action column of Order Details (every open order, including the 09:15 one). Order Details also has **Square off all** (one `squareoff_position` per option).
   - **Confirm popup:** shows the quantity, entry, LTP and approximate P&L. AlgoDelta's `squareoff_position` has **no order ID or quantity**, so it closes the **whole position on that script**. The popup lists the other open orders on the same option, and all of them are marked.
   - **Placing a second order on an option that's already open** asks for confirmation first (option A; there's no hard block).
   - **Not blocked** by Pause algo or the daily limit.
   - **Live:** `sq` = `SENT hh:mm:ss`, the card shows SQUARING OFF, and the trade book is refreshed at once. Exit/P&L then come from Upstox, and the card shows EXITED · Manual. On failure: `FAILED`, with a **Retry square off** button.
   - **Dry run:** Exit = a fresh LTP at the click.
   - **After a square-off:** pair opponent exits and app-watched CANDLE/custom rules are skipped (`engine.squared_off`).
   - **Saved:** `sq` is stored in the orders file.
   - **Verified by the user:** AlgoDelta's square-off closes the position, including its pending SL/Target.
13. **Manual Entry (PR #17):**
   - A 4th Order Management sub-page, `/order-management/manual-entry`, with rows of source `manual`.
   - **Form:** Strike, CE/PE, Lots, **Price / Market / Limit / Stop-limit** (Limit added in PR #20 and the default from PR #21; Stop-limit added in PR #36 and the default since PR #40) and the price (pre-filled with the live LTP from `engine.quote_option`).
   - **Buttons:** **Add card** (set Target/SL/Trail on the card, then ⚡) or **Add & place** (uses the defaults).
   - The card is ready at once (TRIGGERED, no candle checks). **Price** reuses the PENDING entry logic; **Market** sends `strategy_order` now. AlgoDelta holds the SL, Target and trail.
   - Setup has a **Manual entry** default target (`tgt_manual`).
   - **Limit mode** was added in PR #20 (decision 16) through AlgoDelta's `limit_order` and `cancel_order`, with the SL/Target watched by the app. Since 1 April 2026, Upstox order APIs (place/modify/cancel) need a static IP registered in the user's own Upstox app, and AlgoDelta's IP can't be used. With a static IP, an "Upstox direct" mode could add modify and per-order square-off, and keep the SL at the broker.
   - The user checked AlgoDelta's Syntax Generator: `strategy_order` has **no entry-price field**, so the Price mode stays app-side.
14. **Target fix (PR #15):** rows no longer copy the Setup target when they're added (the old `_stamp_target`). The default Target is read from Setup **when the order is placed**, so a Setup change applies to existing rows too.
15. **Order Management sub-pages and cards (PRs #12 to #14):**
   - The nav group has Same strike, Pair, BEP Support ⭐ and Manual Entry.
   - Cards are modelled on AlgoDelta's order card, with a Compact view switch.
   - Entry at a price (PENDING): the app waits for the LTP, then sends a market `strategy_order` (details in Architecture).

16. **Manual Entry Limit mode (PR #20):**
   - **Form:** a third mode, **Price | Market | Limit**, with a "Limit price" field. The form starts on **Limit** (PR #21; it was Price before).
   - **⚡ sends** AlgoDelta `limit_order` (BUY, quantity = lots, the price). Pause algo, dry run and the daily limit apply.
   - **Typo guard:** a popup asks first if the price is ≥ `LIMIT_SANITY_PCT` (20%) away from the LTP.
   - **SL/Target/trail are watched by the app**, not AlgoDelta (`limit_order` has no SL/Target fields):
     - LTP/POINT rules and the trailing SL are checked on the live LTP every 2 s;
     - a CANDLE rule goes to `c_sl`/`c_tgt` (candle path);
     - a hit sends `squareoff_position` once (`mg.exit`);
     - at 15:15: open limits are cancelled, filled ones are squared off.
   - **Live fill:** read from the Upstox **order book** (`/v2/order/retrieve-all`, read-only, no static IP) every `LIMIT_POLL_SECONDS` = 5 s while open. Matching is by instrument, BUY LIMIT, price and time, then the `order_id`. The trade book is refreshed at once after a fill.
   - **Card chips:** LIMIT OPEN @ x → FILLED @ x (· PARTIAL) → EXITED; also CANCELLING, CANCELLED, CANCEL FAILED (Retry cancel) and REJECTED (with the reason).
   - **Cancel:** AlgoDelta `cancel_order` (`{"type":"cancel_order","script_type","script","product"}`) has **no order ID**, so it may cancel every pending order on that option (other limits and the broker SL/Target of open strategy orders). The popup warns about this.
     - Live: CANCEL SENT, then the order book confirms it, else CANCEL FAILED after 30 s.
     - Dry run: CANCELLED at once.
     - A partial fill keeps its filled part protected.
   - **Deleting a card** with an open limit sends `cancel_order` first (user request). A square-off of a partly filled limit cancels the rest first.
   - **Dry run (fixed in PR #23):** fills only in market hours (never before 09:15, when the LTP is stale) at **min(price, live LTP)** once LTP ≤ price, so a gap below the price fills near the LTP. The exit is a fresh LTP via the normal square-off. Placing before 09:15 shows "market not open yet: the limit waits for 09:15".
   - **Exit chip (PR #23):** EXITED · App SL / App trailing SL / App target / 15:15 / Opponent SL / Manual (from `mg.exit`, also set by `square_off`).
   - **Header badge:** "APP-MANAGED SL ACTIVE (n) - keep this PC on" / "LIMIT OPEN (n)".
   - **Restart:** the state is in the orders file (`mg`), so watching resumes.
   - **Order Details:** shows the limit state and app rules in SL/Target, plus a Cancel order action.
   - **Editing after placing (PR #42, user request 23 Nov; it was locked before):** SL, Target and Trailing of a Limit / Stop-limit order are editable while it's pending or filled and not exited (the card boxes and the Order Details popup; `order_rule_editable`). AlgoDelta holds none for these orders, so an edit **replaces** the rule: LTP / POINT → `mg.sl` / `mg.tgt` (live LTP), CANDLE → `c_sl` / `c_tgt` (candle closes), × removes it (`Engine._set_limit_rule`, `order_rule`, `order_trail`). The trail goes to `mg.trail`, and it now also works with only a CANDLE SL (`limit_orders.sl_level`). The "Check the stoploss" warning applies.

17. **Limit for Same strike, Pair and ⭐ (PR #22):**
   - **Choosing the type:**
     - The Same strike and Pair Add forms have an **Order: Strategy | Limit** toggle (default **Strategy**).
     - Each card (Same strike, Pair, ⭐) has the same toggle in its Entry Price box until it's ordered (`CommonWatch.set_mode`, which resets the Entry Price).
     - Compact view has an **Order** column (`Strategy` / `Limit @ x`); click it for a popup.
     - Anything other than Limit sends `strategy_order` (market, or the app-side PENDING entry when an Entry Price is set).
   - **Limit price:**
     - It's the card's Entry Price, pre-filled with the row's level (common price / ⭐ BEP).
     - Pair before it fires: the fired leg's own price (`Engine.limit_price`).
     - Editing a Same-strike level moves a limit price that was still equal to the level.
   - **Sending:** ⚡ works only once TRIGGERED. The order goes through `place_limit_order` (the same app-watched SL/Target/trail as Manual Limit, using the per-type default targets).
   - **Auto-cancel:**
     - A card that turns FAILED/EXITED cancels its open limit (`cancel_dead_limits`, each scan); a filled part stays protected.
     - Pair opponent exit: a filled limit is squared off and an open one is cancelled (`handle_pair_exits`).
     - Delete and 15:15 work as for Manual.

18. **App trailing SL and editing after placing (PR #24):**
   - **CANDLE SL + trailing:** the card's trail (own or Setup) is no longer forced OFF. It's stored on the order as `c_trail` (`{"trigger","gap","step","set_at","high","done"}`, a new orders-file column) and watched by the app on the **live LTP every 2 s** (`check_app_trails`).
     - The rule: once the high reaches entry + trigger, SL = high − gap (steps of point), and it never moves down.
     - LTP ≤ SL → `squareoff_position` **once** ("App trailing SL").
     - Entry = the order's Entry (Upstox fill live, signal LTP in dry run).
     - The CANDLE SL is still checked on candle closes; whichever hits first exits.
   - **Ordered, still-open cards (not limit orders, not the 09:15 order)** are editable while open:
     - Target / Stoploss: a click opens the rule popup and sets an app-watched rule (`set_order_custom`, the same as Order Details).
     - Trailing: a click opens the trail popup (`set_order_trail`; Remove clears it).
     - AlgoDelta's original SL/Target/trail stay active (no modify syntax); whichever hits first exits.
   - **Order Details:** the SL/Target popup gains **Set trailing / Change**, and the SL/Target column shows `Trail a/b (app) · SL x`.
   - **Dry run:** the same check on the live LTP; the exit is a fresh LTP via the square-off.

19. **Card box names (PR #26):**
   - The level box is named per type (`level_name`): **Common price** (Same strike), **Pair price**, **BEP** (⭐) and **Order type** (Manual: Market / Price / Limit, from `manual_type`).
   - The first box is **Entry Price** before ordering and **Entry (filled)** after.
   - The Compact view Level column uses the same names; Manual rows show their order type.
   - **SL after placing (discussed, left as is by the user):** an app rule set after ⚡ only **adds** an exit, because AlgoDelta's original SL (e.g. 12 POINT) stays active with no modify syntax. To use only a CANDLE SL, set it **before** ⚡. Offered but not built: show both SLs on ordered cards, warn in the popup, and a Setup "SL held by AlgoDelta / App" switch.

20. **Arming on a touch, Trigger on Live LTP, 1 min (PR #27; Same strike and Pair):**
   - **Why:** the user's Pair (25500CE/25750PE @ 196) never fired. The CE was already above 196 when added and never **closed** back at or below it within 5 min.
   - **Armed:** a leg is armed once it trades at or below its price after the row is added: a candle close, a candle **low** (wick) of a candle that started after the add, or the **live LTP** (every 2 s, `CommonWatch.live_step` via `engine.check_live_watch`). Same strike rows now have `armed` too. Cards and Compact status show "armed / not armed yet".
   - **Trigger on** (per row `trig_on`; toggle on both forms and in Edit, default **Candle close**):
     - **Candle close:** an armed leg's candle closes above the price (Pair: the opponent's close below price − buffer).
     - **Live LTP:** an armed leg's LTP goes above the price (Pair: the opponent's LTP below price − buffer), within ~2 s (`trig_how` = "ltp", `trig_time` HH:MM:SS).
   - FAILED and the Pair opponent exit stay on candle closes.
   - **Timeframes:** 1 / 3 / 5 min (forms and Edit). Editing a row restarts arming.
   - Nothing is placed automatically: a trigger means alert + TRIGGERED, then ⚡.
   - "Arm now" (count a leg already above as armed) was declined.

21. **LTP on the Same strike and Pair forms (PR #28):**
   - An **LTP** box with a ↻ button (`form_ltp`), like Manual Entry's: Same strike shows the chosen leg(s) (Both → `CE x · PE y`); Pair shows the CE strike's CE LTP and the PE strike's PE LTP.
   - It refreshes on strike blur, on a leg change, with ↻, and once when the page opens (`engine.quote_option`).
   - The Common price is **not** pre-filled with the LTP (it's a level the user chooses).

22. **Open (live) P&L, calculated locally (PR #29):**
   - Before this, P&L showed only after the exit (0 while open).
   - Open position: **(live LTP − Entry) × qty** (`Engine.open_pnl`), qty = filled units (live) or lots × lot size.
   - **No extra API call:** the LTP is the one 2 s batch (`refresh_option_ltps`, which now covers every open order and updates its `ltp_live`). `trade_tracker.compute(..., known=option_ltp)` only fetches options not in that batch.
   - **Cards:** P&L in green/red with `+x pts · open`; the realized P&L after the exit.
   - **Order Details:** the Captured Points / P&L ₹ columns show `x (open)` for open orders (`open_points`/`open_pnl`, not saved), and the summary adds "open n: P&L ₹x" (the closed totals are unchanged).
   - Upstox is still needed for the LTP itself and for live fills/exits (trade book every 30 s).

23. **Pre-place / SL safety warnings (PR #30):**
   - **Why:** a Same strike card (level 120) was placed at 14:03 with LTP 111 and a CANDLE SL of 120. The next 5-min close (109.30 < 120) exited at once.
   - **At ⚡ ("Check before placing", Place anyway / Cancel; after the limit typo guard, before the same-option confirm):**
     - an SL (the card's own, else Setup's) of type LTP/CANDLE **at or above** the price you buy at (the LTP, the Entry Price or the limit price);
     - the LTP is **already back below** the row's level (Common price / Pair price / BEP): "the setup may have failed". Not for Manual cards.
   - **Setting an SL after placing** (the ordered card or the Order Details popup): "Check the stoploss" when it's at or above the Entry (`guarded_sl_set`).
   - POINT SLs are always below the entry, so they're never flagged.
   - **Far above BEP (PR #43, user request 23 Nov):** on ⭐, BEP cross Pair (fired leg) and Manual Entry cards (the strike's BEP from the CSV, else calculated; `Engine.row_bep`), the popup adds "LTP 168.70 is **11.13 points above** BEP 157.57 (warning above 10): late entry, bigger risk to the SL" when LTP − BEP > Setup **"Warn at ⚡ when LTP is more than X points above BEP"** (`warn_above_bep`, default 10; 0 = off). For Limit / Stop-limit the limit price is checked the same way. **Fix (user, 26 Nov, both apps):** for Limit / Stop-limit cards **only the limit price** is checked, not the LTP (a Limit 226 with BEP 223.80 and LTP 243.25 warned "LTP is 19.45 points above BEP" although the order buys at 226). A Strategy card with an **Entry Price** is checked at that Entry Price ("Entry price 230.00 is … above BEP"); a plain Strategy (market) card still at the LTP. Same strike and normal Pair cards (own levels) and the automatic 09:15 order (its own `max_above_bep`) are not affected.

24. **BEP Support setup fixes (PR #32):** in `support_logic.process_candle` (5-min candles).
   - **Setup break and expiry:** a validated "Failed breakdown" setup is **broken** when a later candle's low goes below the flush low. It **expires** `SUPPORT_SETUP_EXPIRY_CANDLES` = 3 candles (15 min) after the validate candle. A trigger whose own low breaks the flush low is "Touch and go" (fail level = its own low).
   - **New flush:** a candle that resets a flush or setup and itself **closed below BEP** starts a **new flush**.
   - **09:15 exception:** the validate low may break the flush low only when the **flush candle** is 09:15 (the old check never ran).
   - **Follow-ups decided after the review (PR #33):**
     - **Repeat alerts:** a support alerts (and adds a ⭐) for the first row of a strike/side, and again once every earlier row on that strike has **failed** (`row["star"]`; the board's ⭐ marks those rows).
     - **First support card:** only strikes inside that candle's ATM window count; on a tie in the same candle, the strike **nearest ATM** wins.
     - **A missing candle** (never arrived, given up, or no BEP) resets that leg to idle.
     - The trigger keeps its +0.05 tolerance and the fail rule none (kept as is).
     - 09:15 order: `max_above_bep` **0 = no limit**.

25. **BEP Pair cross, Pair auto-add and Replay (PR #33):**
   - **What:** on each closed 5-min candle (the board's candles, no extra API calls), a CE and a PE near ATM that **split around their BEPs**. It's independent of the Support board and ⭐. Examples from the user: 20 Nov 09:45 25450CE/25450PE (same strike, full body) and 11:35 25500CE/25550PE (different strikes, wicks).
   - **Pairs:** ATM = the strike nearest NIFTY's close of that candle.
     - **Buy CE:** the leg above (the one to buy) is the CE at ATM or up to **2 strikes ITM** (ATM − 50, ATM − 100; `BEP_CROSS_ITM_STRIKES` = 2, PR #35; it was 1); the opponent below is the PE at ATM − 50, ATM or ATM + 50.
     - **Buy PE:** the leg above is the PE at ATM or up to 2 strikes ITM (ATM + 50, ATM + 100); the opponent is the CE at ATM ± 50.
     - **Why 2 (PR #35):** on 20 Nov at 09:40, 25400CE closed above its BEP and 25450PE below, but NIFTY was about 25,485 (ATM 25500), so 25400 was 2 strikes ITM and was never checked. The user confirmed on the 20 Nov replay (after PR #35) that the 09:40 row now shows.
   - **Signal:** the up-leg closes > its BEP **and** the down-leg closes < its BEP, and the previous candle wasn't in that state. Either leg may have crossed first (e.g. PE below at 09:40, CE above at 09:45). A pair already split on the first candle counts. No margin past BEP.
   - **Touch (user request):** both legs must have **touched** their BEP (low ≤ BEP + `BEP_CROSS_TOUCH_TOL` = 1 and high ≥ BEP − 1) on the signal candle or the 2 before (`BEP_CROSS_TOUCH_CANDLES` = 3). A leg far away from its BEP doesn't count.
   - **Labels (PR #35, the user is an option buyer and never shorts):** the Signal column shows a **Buy CE** (green) / **Buy PE** (red) badge (no ↑/↓ arrows); the columns are "Buy leg (closed above BEP)" and "Opponent (closed below BEP)"; Pts since / Best are for the **buy leg only**; alerts read "BUY 25400CE … | opponent 25450PE …".
   - **"Why no row?" checker (PR #35):** CE strike, PE strike, candle HH:MM + Check on the BEP Pair cross page (today or the replayed day). It lists each rule as ✓/✗ (`PairCross.explain` via `BepMonitor.explain_cross`): candles/BEPs, split, buy leg in range (NIFTY close, ATM), opponent in range, fresh, touch of each leg (times), already WATCHING, or signalled (main row or "Also").
   - **Rows:** one per candle and direction. The best pair is the same strike first, else the smallest BEP gap; the others go in "Also". No new row for a pair while it's WATCHING; after FAILED it can signal again.
   - **Watch 30 min** (`BEP_CROSS_WATCH_CANDLES` = 6): FAILED · time if the up-leg closes below its BEP or the down-leg closes above its BEP, else HELD. The table shows the best move of each leg and live LTPs (the 2 s batch) while watching.
   - **Alerts:** a toast + browser notification **only on a live signal** (respects Pause alerts). Rows rebuilt after a late start don't alert.
   - **Order Management > Pair (Part C):** a live signal adds a **TRIGGERED** Pair row (`add_cross_pair`), unless `BEP_CROSS_ADD_PAIR` is False.
     - CE/PE price = each leg's BEP, **buffer 0**, 5 min, Strategy, the up-leg is the fired leg, chip "BEP cross hh:mm".
     - Later candles use the normal Pair rules (opponent closing at or above its BEP = FAILED before ordering, opponent SL after).
     - A table FAILED marks it FAILED before ⚡ (`sync_cross_failures`, run before new rows are added).
     - It's skipped (logged) when a Pair row with the same strikes is still watching/triggered. Nothing is placed automatically.
   - **Replay a past day (Part E):** a date + "BEP: uploaded CSV / calculated" + Replay on both BEP Support pages.
     - It rebuilds the Support board and the Pair cross from Upstox **historical** candles in a separate monitor: no alerts, no ⭐ / Pair rows, no orders, and the live scan keeps running. "Back to live" returns. Downloads include "_replay".
     - Only days since the last expiry (older contracts aren't listed). The CSV must be **that day's** file; calculated = (CE + PE) / 2 of the previous day's closes (`fetch_close_before`, 2 calls per strike, ATM windows only).
     - Not available on non-trading days for "today": the board only reads today's intraday candles, so on a weekend the live board is empty (the user asked on Sat 21 Nov).

26. **Short toasts, top-right (PR #36):** the user said the long toasts covered the screen at the moment of the signal.
   - Toasts are top-right below the header, max 360 px wide, shown for 8 s, with a ✕ (`app.py` `pump_events`, CSS `.bep-toast`).
   - The text is short: `⭐ Support 26200PE · touch and go`, `Pair cross: BUY 25950PE · opp 25900CE`, `Pair 25450CE/25450PE: CE triggered → Place order` (`notifier.support_short` / `cross_short` / `common_short`). BEP, close and time are in the tables.
   - Alerts of one type in one scan are merged into **one** toast (e.g. `⭐ Support PE: 26200, 26100, 26050 · touch and go`).
   - The browser notification shows the same short text; the **full** labels still go to the Log.
   - Other toasts (order results, form messages) keep their text but use the same position and size.
27. **BEP box on BEP cross Pair cards (PR #36):** the user wants the BEP next to the live LTP, to compare.
   - Rows added by a BEP cross (`auto` = "cross") name the level box **BEP** (not "Pair price"): `CE 137.32` / `PE 126.15` on two lines, each with its live **LTP − BEP** (`+9.03 above` green / `-23.35 below` red, the 2 s LTP batch, `cross_bep_gaps`).
   - The header chip / Compact Pair column read `25600CE / 25650PE · BEP 137.32 / 126.15` (`CommonWatch.pair_title`).
   - Pair cards (all) show the LTP as `CE x` / `PE y` on two lines (the one-line text overlapped the next box).
   - Manual Pair rows keep "Pair price" (the user's own levels).
28. **Stop-limit entry and the limit-above-LTP warning (PR #36):**
   - **Why:** the user set a Manual BUY **Limit 140** with the LTP at 134.65 and it filled at once. A BUY limit means "at 140 **or cheaper**". What they wanted was a broker **Buy StopLimit**: wait until the price **rises** to 140.
   - **AlgoDelta `sl_order`** (checked by the user in the Syntax Generator, 23 Nov 2026): `{"type":"sl_order","script_type","script","product","quantity","price","trigger_price","transaction_type":"BUY"}`. It waits **at the exchange** (Upstox status "trigger pending") until LTP ≥ trigger, then it's a limit at `price`.
   - **Manual Entry:** a 4th mode, **Price | Market | Limit | Stop-limit**, with **Trigger (LTP rises to)** and **Limit price** (default trigger + `STOP_LIMIT_GAP` = 1, editable). The row stays `entry_mode` "limit" with **`entry_trigger`** set, so everything else is the Limit flow (decision 16): app-watched SL/Target/trail, order-book fill tracking, cancel, Delete, 15:15.
     - The card's Entry box has two inputs (trigger → limit). The Order type box shows **Stop-limit** with "at LTP ≥ x, limit y".
     - The chip shows `STOP @ 140.00 → LIMIT 141.00` until triggered, then `LIMIT OPEN @ 141.00` → `FILLED @ x`.
     - ⚡ is refused when the LTP is already ≥ the trigger (it would trigger at once): raise the trigger, or use Limit / Market.
   - **`limit_orders`:** `mg.trigger` / `mg.triggered`. The order book is matched on `order_type` "SL" plus the trigger price. "trigger pending" = waiting; any other open status, or a fill, = triggered.
     - **Dry run:** triggers when the live LTP ≥ the trigger, then fills once LTP ≤ the limit, at min(limit, LTP). A spike past the limit stays open, like a real stop-limit.
   - **Limit-above-LTP warning (all Limit cards):** ⚡ on a BUY limit above the LTP asks "This limit fills immediately", with **Send limit anyway** / **Switch to Stop-limit** (Manual cards: trigger = the price, limit = price + 1; then check the card and ⚡ again) / Cancel. It replaces the 20 % typo popup in that case; stop-limits skip the typo popup.
   - **Stop-limit on Same strike, Pair and ⭐ cards (PR #38, user request on 23 Nov):** every Order toggle (Add forms, card, Compact dialog) is **Strategy | Limit | Stop-limit**.
     - The row keeps `entry_mode` "limit" plus **`entry_stop`** = True. The trigger defaults to the row's level (⭐ = BEP; Pair = the **fired leg's** price, known once it fires) and the limit to trigger + 1. Both are editable on the card (`entry_trigger` / `entry_price` once set). Helpers: `Engine.is_stop` / `Engine.stop_prices`.
     - A Same-strike level edit moves a trigger that was still equal to the level.
     - All Pair rules stay: opponent exit (squares off a filled order, cancels a pending one), FAILED cancels it, 15:15, Delete.
     - At ⚡: no "price back below the level" warning (a stop-limit waits for the rise). It's refused when the LTP is already ≥ the trigger. **Switch to Stop-limit** in the limit-above-LTP popup now works on every card.
     - **Trigger / limit popup (PR #45, user request 23 Nov):** choosing Stop-limit on a card (or in the Compact Order popup) opens **"Stop-limit — strike"** with the live LTP and the level / BEP, **Trigger (LTP rises to)** and **Limit price**. The trigger starts at the level only when it's above the LTP, otherwise empty with "must be above the LTP x (the BEP y is already below it)"; the limit follows as trigger + 1. Save checks trigger > LTP and limit ≥ trigger; Cancel keeps the old type. The card shows `trigger → limit` as a clickable label that reopens the popup (no inline boxes). A Pair not fired yet may stay empty (= the fired leg's price at ⚡). `stoplimit_dialog` in `app.py`. Why: a ⭐ at 12:50 (BEP 137.32, LTP 151.95) took the BEP as the trigger, which ⚡ would refuse.
     - Example: the 23 Nov 10:15 BEP cross 25500CE (BEP 167.57, LTP 156.60): Stop-limit sends `sl_order` trigger 167.57 → limit 168.57 and waits for the CE to rise back above its BEP.
     - Merged 23 Nov 2026; the user confirmed Stop-limit shows on Pair cards.
   - **Manual Entry default = Stop-limit (PR #40, user request 23 Nov):** the form opens on Stop-limit. The trigger is **not** pre-filled (it must be above the LTP; the LTP shows beside it); typing it fills the limit = trigger + 1. The LTP pre-fill of the price box now applies only to Price / Limit.
   - **Form check (user, 25 Nov, all suggested):** Add card / Add & place refuse a Stop-limit whose trigger is at or below a **fresh LTP** (quoted at the click): "Stop-limit: the trigger 190.00 must be above the LTP 238.65. To buy on a dip, use Limit or Price." No LTP (not connected) → the card is added and ⚡ still checks. Why: a 190 trigger with LTP 238.65 was added and only ⚡ refused it. (Both apps.)
   - **Not yet tested live:** AlgoDelta `sl_order` → Upstox (order_type "SL", status names), and what `cancel_order` does to a trigger-pending order. Test with 1 lot. Merged 23 Nov 2026; the user confirmed the card shows correctly and planned the 1-lot live test on 24 Nov, but 24 Nov is a market holiday, so it moves to the next trading day.

29. **Manual Entry BEP and Target "None" (PR #48, user request 23 Nov):**
   - **BEP on the Manual Entry form:** next to the LTP, `BEP 157.57 (+11.13)` (LTP − BEP, green above / red below). It comes from the uploaded CSV, else calculated (`Engine.row_bep`). It refreshes with the LTP (strike blur, CE/PE change, ↻) and once when the page opens. Shown only, no check; the ⚡ "far above BEP" warning (decision 23) stays.
   - **Target type None** (the user trails and wants bigger targets without changing the Setup default): the Target popup on every card (Same strike, Pair, ⭐, Manual; card box and Compact view) has **LTP / POINT / CANDLE / None**. It's stored as a `c_tgt` rule of type `NONE` (`exit_rules.NONE`, `is_none`; never evaluated). Switch OFF / × still means the Setup default.
     - Strategy order: sent with `is_tgt` false (AlgoDelta holds no target). Limit / Stop-limit: no app target (`_limit_rules`). Dry run simulates no target.
     - After placing: Limit / Stop-limit orders can be set to None (= remove the target, `_set_limit_rule`). Strategy orders can't (AlgoDelta's target was sent, no modify syntax), so the popup there has no None. An ordered card sent with None shows "None · no target (trail / SL only)".
     - At ⚡: "Check before placing" adds "Target is None and the trailing SL is OFF: this order exits only by the SL, a manual square-off or 15:15" when the card's trail is off.
     - The 09:15 order is unchanged (Setup target).

30. **NIFTY change % in the header (user, 24 Nov; the same change in BEP_Upstox, its decision 9).** The header chip shows `NIFTY 26,050.35  +448.10 (+1.75%)`, green up / red down. `Engine.fetch_index_ltps` uses the Upstox **full market quote** (`GET /v2/market-quote/quotes`, `upstox_client.fetch_quote`: `last_price` + `net_change`) instead of the LTP call: the same one call per scan. % = net change ÷ (LTP − net change) × 100 (`Engine.index_change`). Before 09:15 and on holidays it is the last session's change (on 24 Nov it should read +1.75 %). If the full quote fails: the plain LTP call, no change for that scan, one Log line. Header only.

31. **Max loss per day (PR #52, merged 24 Nov; user, 24 Nov; the same in BEP_Upstox, its decision 10 / PR 7; all suggested).** Setup › Trading **"Max loss per day (₹, 0 = off; Dry run only for now)"** (`max_loss_day` in `AUTO_ORDER`, default 2000, saved in settings.json when you leave the box). **For now only in Dry run** (Live later, after testing): day loss = today's closed + open P&L of the **DRY RUN** orders (`Engine.max_loss_state`); the limit is hit at a loss ≥ the value.
   - **⚡ / Add & place** (first of the ⚡ checks): popup "Max loss per day reached: Day loss ₹2,350 is past your max loss ₹2,000", **Place anyway** / Cancel. Place anyway marks the card (`loss_ok`, `Engine.ack_max_loss`, logged), so a PENDING entry armed then still fires.
   - **Orders nobody clicks** (a PENDING card firing later): not placed, card BLOCKED (⚡ can be pressed again), toast + Log "Max loss per day reached (loss ₹x, limit ₹y); NOT sent" (`Engine._max_loss_block`, before `send_order` / `send_limit` of a card).
   - **The 09:15 order is not affected** (user: "This loss limit is not applicable for 9:15 order"; `dispatch_orders` doesn't check it). Open positions are left alone (no auto square-off).
   - Header: a red **MAX LOSS ₹2,350 / 2,000** badge once hit.

32. **09:15 second-side window (TESTING feature, user 24 Nov; BEP-AlgoDelta only, all suggested).** Once one side (CE or PE) has its 09:15 order, the other side may follow only within **`open_second_side_secs`** (60 s) of that order's time (e.g. CE at 09:15:20 → PE allowed until 09:16:20). After that, the other side is **restricted** for the day (`BepMonitor._restrict_second_side`, run at the start of each `opening_tick`; lock status `restricted`).
   - Only orders that lock a side start the window (SENT / DRY RUN / FAILED). BLOCKED frees the side, so it doesn't.
   - Both qualifying in the same second or within 60 s → both are placed.
   - Log line: "PE 09:15 order restricted: CE was ordered at 09:15:20, more than 60 s ago". Dashboard 09:15 status: "PE: restricted (CE at 09:15:20)".
   - Setup: a **"09:15 second side window" switch** (ON by default; `open_second_side`) + **"Second side within (seconds)"** (60, > 0, greyed out when OFF; `open_second_side_secs`), both saved in settings.json. OFF = the old behaviour (each side any time 09:15–09:20). (The first version used 0 = off; the user asked for a switch instead.)
   - A restart reads the first order's time back from today's orders file, so the window still applies.
   - Only the automatic 09:15 order is affected: a restricted side does **not** skip the 09:15 ⭐ row (only a real 09:15 order does).
   - **Not ported to BEP_Upstox yet** (user: testing feature; recorded in BEP_Upstox's CLAUDE.md "to port later").
   - Checked: a simulated tick with CE at 09:15:20 → PE at 09:15:50 placed, PE at 09:16:30 restricted, with the switch OFF placed; the Setup page shows the field.

33. **Setup layout in bordered sections (user, 24 Nov; also BEP_Upstox, its decision 11; all suggested).** No setting changed, only where it sits. `setup_section(title, icon, classes)` in `app.py` = a bordered card (`flat bordered`) with a title row.
   - Top row: **Upstox**, **BEP files**, **Scanner**, **Trading** (min width 250 px so all four fit on one row on a wide screen). Trading's max loss box is "Max loss per day ₹ (0 = off)" with the note "Dry run only for now; the 09:15 order is not affected" below it.
   - **NIFTY — AlgoDelta order settings**, two per row: **AlgoDelta connection** (webhook, JSON template, "I checked this JSON") · **Default order (all orders)** (quantity, Target, SL, Trailing SL, Exit on opposite) · **Order Management** (per-type default targets, Warn at ⚡ above BEP) · **09:15 opening order** (max above BEP, entry / SL / candle, max SL, second-side window). One **Save** + Preview JSON at the bottom, as before.

34. **The 09:15 order's own trailing SL (user, 24 Nov; also BEP_Upstox, its decision 12; suggested except the defaults).**
   - **Setup › 09:15 opening order:** a **"09:15 trailing SL" switch, ON by default**, with **Trigger 20, Point 1, Gap 19** (`open_trail`, `open_trail_trigger` / `_point` / `_gap`, saved in settings.json; Gap ≤ Trigger). It replaces the Default order trail for the 09:15 order (that one still applies to Order Management cards). Watched by the app as `c_trail` (`BepMonitor._opening_sl`); AlgoDelta's max SL stays fixed.
   - **Order Details:** the open 09:15 order's SL / Target button opens **only the trailing popup** (`opening_trail_dialog`): Set / Change / Remove, until it exits or is squared off (`Engine.order_trail_editable`, `is_opening`). The candle SL, AlgoDelta's max SL and the Target can't be changed there.
   - **A change never moves the SL down:** the new trail keeps the high seen so far (and the current LTP) and the old level as a `floor` (`Engine.trail_level`). E.g. entry 152, high 180, trail 20/19 → SL 161; changed to 30/25 → stays 161; changed to 10/5 → 175.
   - **"Check the stoploss":** when the new SL would be at or above the LTP (an exit at once), the popup asks first (Set anyway / Cancel).
   - Checked: the signal carries the 09:15 trail (and none when OFF); the engine path above; Setup shows the fields; Order Details changed 20/19 → 30/25 with no page errors.

35. **09:15: skip the first signal (TESTING feature, user 25 Nov: option A, all suggested; BEP-AlgoDelta only).** Each side's (CE / PE) **1st** 09:15 signal is not ordered; the order goes on the **2nd** (`open_skip_first`, `BepMonitor._first_skip`, in `opening_tick`).
   - **2nd signal:** a strike of that side whose LTP fell back **below its entry level** (BEP + `open_entry_above`) after the 1st signal and then meets **all** the rules again (touch, LTP > open, ≥ BEP + 2, < BEP + 15). Per side, either strike (the nearer one wins as before); a strike that stayed above since the 1st signal doesn't count.
   - No 2nd signal by 09:20 → no 09:15 order for that side that day.
   - Log: "CE 26000 1st signal skipped (LTP 153.00 >= BEP 150.00 + 2); waiting for the 2nd …". Dashboard: "CE: 1st signal skipped at 09:15:20 (26000), waiting for the 2nd" (after 09:20: "no 2nd signal").
   - Setup › 09:15 opening order: **"09:15: skip the first signal"** switch, **ON by default**, saved. OFF = order on the 1st signal.
   - The 60 s second-side window (decision 32) starts from the first order actually placed, not from a skipped signal.
   - The skip state is in memory: a restart between the 1st and 2nd signal starts over (the next signal counts as a 1st).
   - **Not ported to BEP_Upstox** (recorded there under "To port later").
   - Checked (simulated ticks): skip → dip → 2nd ordered; the other strike staying above isn't a 2nd signal; no dip → no order; switch OFF → 1st ordered; with the 60 s window: PE 2nd 50 s after the CE order placed, 70 s after restricted. Setup shows the switch and saves.
   - **Discussed, kept for later (user, 25 Nov):** the "LTP > open" rule when the candle opens above the BEP (e.g. BEP 150, open 165: no price meets both LTP > 165 and < BEP + 15, so no order). Options offered: a Setup switch for "LTP > open", or a higher max above BEP.

36. **Target held by the app for Order Management Strategy orders (user, 25 Nov: option 2, all suggested; BEP-AlgoDelta only).**
   - **Why:** a ⭐ order (25800CE, entry 327.45, default Target 30 POINT) was changed to Target 100 after ⚡, but exited at +30 (357.45): AlgoDelta held the 30-pt target it was sent (no modify syntax) and the app rule was only an extra exit. An SL change worked only because it was raised (tighter than AlgoDelta's).
   - **Now:** every Strategy order from Same strike, Pair, ⭐ and Manual (Market / Price, PENDING entries too) is sent with **`is_tgt` false**. The target (the card's own, else the Setup default for its type) goes on the order as `c_tgt` at ⚡ (`Engine.place_watch_order`). The SL and trailing SL still go to AlgoDelta as before. **The 09:15 order is unchanged** (Setup target held by AlgoDelta).
   - **Watching:** LTP / POINT targets on the live LTP every 2 s (`Engine.check_app_targets`, after `check_app_trails`; POINT = entry + value, `app_target_level`); hit → `squareoff_position` once, `c_tgt.done`, card chip **EXITED · App target** (`Engine.exit_label`, also "App trailing SL" / "Manual" / the dry-run exit reason). CANDLE targets stay on candle closes (trade_tracker). Dry run: the same (exit = fresh LTP via the square-off); the 1-min candle simulation no longer has an AlgoDelta target (`base_rules`, is_tgt false), whichever of the two hits first.
   - **Editing after placing** (card Target box, Order Details popup): a new Target **replaces** it (raise, lower, CANDLE); **None** is offered and, like ×, means no target at all (`set_order_custom`, `Engine.app_target`). Card text "100 pts · at 427.45 · app" / "None · no target (trail / SL only)"; Order Details "Tgt 100 pts (app)" / "Tgt none (app)".
   - Header badge: **"APP-MANAGED SL / TARGET ACTIVE (n) - keep this PC on"** also counts open strategy orders with an app target (`limit_active`).
   - **Risks accepted:** with the PC / app off nothing exits at the target (the SL stays with AlgoDelta); `squareoff_position` closes the whole position on that option (other open orders on it too).
   - Orders placed before this change keep AlgoDelta's target (old behaviour: an app target only adds an exit). Orders sent earlier with Target None count as app-target orders (no AlgoDelta target either).
   - **Not in BEP_Upstox** (its target is already app-held and replaceable).
   - Checked (simulated, dry run): default 30 pts → `is_tgt` false + `c_tgt` 30 POINT, badge 1; changed to 100 → no exit at 357.50, exit at 427.60 "App target"; None → no target, badge 0; card CANDLE target → `c_tgt` CANDLE; Manual Entry and Order Details pages render without errors.

37. **Pair "Auto at 09:15" (user, 25 Nov: all suggested; BOTH apps).** A Pair row can place its order by itself at the open, next to the automatic 09:15 BEP order.
   - **Switch** "Auto at 09:15" on the Pair Add form and on a WAITING Pair card (default OFF; `auto_open`, `CommonWatch.set_auto`, `Engine.set_watch_auto`). Never on BEP cross rows.
   - **Rule (09:15:00–09:20:00, `config.PAIR_AUTO_FROM` / `PAIR_AUTO_TO`, live LTP every 2 s, `CommonWatch.live_step`):** the first leg whose LTP **crosses above** its price is ordered: it must be at or below its price at some point from 09:15 (`legs[o].auto_below`), then above. No opponent check, no candle close. A leg that opens above and never comes down doesn't count. Both in the same check → the one more points above. `trig_how` = "auto"; card chip **AUTO hh:mm:ss**; status "AUTO: CE LTP crossed above 200 at 09:15:06".
   - During the window the row's normal triggers (candle close / live LTP with the opponent rule) are off. **No cross by 09:20 → a normal Pair row** (alert + ⚡, its own Trigger on / Timeframe).
   - **Order (`Engine.auto_place`):** the row's Order type (Strategy market / Limit / Stop-limit / Entry Price → armed) and its own Target / SL / Trail, else the Setup defaults. Then a normal ordered Pair card (SL / Target / Trail, editable, Square off, opponent exit).
   - **No popups:** the ⚡ warnings (SL at / above the LTP, Target None + trail OFF) are only logged. **Skipped** (alert + Log, card stays TRIGGERED for ⚡) when the same option already has an open order or an entry sent but not filled (e.g. the 09:15 order), or a Stop-limit trigger is already at / below the LTP. Pause algo, the daily limit and max loss per day block it as usual (BLOCKED).
   - Alert: toast + notification "NIFTY AUTO ORDER Pair 25800CE / 25800PE @ 200: 25800CE DRY RUN" and Log lines.
   - Checked (simulated ticks, dry run, both apps): no order before 09:15; CE above but not crossed → nothing; CE dips to 199 then 203 → ordered; gap-up row → nothing, normal Pair after 09:20; same option open → skipped; both crossing → the bigger move; switch OFF → nothing; Pair page renders the switch / AUTO chip without errors. BEP_Upstox: 58 unit tests pass.
   - **Window extended to 09:30 (user, 26 Nov: all suggested; both apps).** `config.PAIR_AUTO_TO` = "09:30:00" (fixed; a Setup box can come later). Only the Pair auto window: the automatic 09:15 BEP order keeps 09:15–09:20. The row's normal triggers stay off until 09:30; the timeframe / Trigger on only matter after the window (the auto rule is live LTP every 2 s). Texts read the times from config. Checked (simulated, dry run, both apps): a cross at 09:24 is ordered (AUTO); after 09:30 the row is a normal Pair.

38. **GIFT Nifty in the header (user, 26 Nov: all suggested; BOTH apps).** A second header chip next to NIFTY: `GIFT NIFTY 26,120.50 +45.00 (+0.17%) +70.00 vs NIFTY` (green up / red down; the gap = GIFT − NIFTY LTP). `gift_nifty.py` (the same file in both apps): the key is read once a day from Upstox's Global Instruments file (`assets.upstox.com/market-quote/instruments/exchange/global.json.gz`, segment `GLOBAL_INDEX`, no token), else `GLOBAL_INDEX|SGX NIFTY` (the documented example); the quote is the same full-quote call as NIFTY (LTP + net change; the LTP call if that fails), every 30 s in its own task (`Engine.refresh_gift`, never delays the scan). Upstox refreshes GIFT Nifty only about every 120 s; its hours are about 06:30–02:45 IST Mon–Fri. The chip greys out after 5 min without a change (holiday / outside GIFT hours); hover = last change / checked time; a failure shows `GIFT NIFTY --` and one Log line (the key used is logged at the first call). Header only: no trading logic reads it. Checked: 5 unit tests (`tests/test_gift_nifty.py`, fake client) and the header in both apps. **Not yet seen against the real Upstox API** (the global file could not be downloaded from the cloud session): check the Log line with the key on the next start.

39. **SL set after ⚡ checked on the live LTP (user, 26 Nov: all suggested; BEP-AlgoDelta only).** Why: a ⭐ order (25850PE, entry 219.35) got SL 250 (LTP) after ⚡ with the LTP at 244.85 and exited only 1–2 min later: an SL set after placing (`c_sl`) was checked only on 1-min candles by `trade_tracker` (from the candle after the minute it was set), and the dry-run exit was recorded at the level (250), not the real price. Now LTP / POINT SLs set after placing a Strategy order are watched every 2 s on the live LTP (`Engine.check_app_sls`, after `check_app_targets`; POINT = entry − value, `app_sl_level`): LTP ≤ level → `squareoff_position` once, `c_sl.done`, chip **EXITED · App SL** (`exit_label`); dry run exits at a fresh LTP via the square-off. AlgoDelta's own SL stays active (no modify syntax): whichever hits first. CANDLE SLs stay on candle closes. `trade_tracker.custom_rules` returns only CANDLE rules for strategy orders now (their LTP / POINT SL and target are both live-watched; no late candle exit, no dry-run exit at the level). Limit / Stop-limit orders unchanged (their rules live in `mg`). Not in BEP_Upstox (a new SL there moves the exchange SL order). Checked (simulated, dry run): SL 250 LTP at 260 → open, at 244.85 → exit 244.85 "App SL"; POINT 10 from 100 → exit at 90; a CANDLE SL is not exited on the LTP.

40. **Pair card: only the fired leg (user, 26 Nov; both apps).** Once a Pair leg has fired (TRIGGERED / ordered), the card shows **only that leg**: the LTP box (`card_ltp_text`), the BEP box of BEP-cross rows (`cross_bep_gaps` filtered) and the Pair price box (when the legs' prices differ) hide the opponent; the header symbol of the fired leg is bigger (`text-xl`); the chip reads just "CE fired" (hover: the full pair and "the other leg is still watched for the opponent rule"). Before a leg fires both legs show as before. Display only: the opponent rule (FAILED before ⚡, opponent SL after) is unchanged. Compact view unchanged. Checked: the Pair page in both apps with a waiting pair, a fired normal pair and a fired BEP-cross pair, no page errors.

41. **09:15 BEP order switch + "No trade today" (user, 26 Nov: all suggested + option A; both apps).** Setup › 09:15 opening order: a **"09:15 BEP order" switch, OFF by default** (`open_order_on`, saved in settings.json at once, `Engine.set_opening_order`) and a **"No trade today"** checkbox (enabled only with the switch ON; `open_skip_date` = today, `Engine.set_skip_today`; skips only that day's 09:15 order and resets by itself the next day). `BepMonitor.opening_off(day)` gives the reason; in `opening_tick` a qualifying side is then **not ordered**: one Log line "CE 26000 09:15 signal (LTP x, BEP y) - NOT ordered (09:15 order OFF (Setup) / No trade today)" and the Dashboard 09:15 card reads "09:15 order: OFF (Setup) — CE: 26000 signal at 09:15:20, not ordered" (or "skipped today"). The 09:08 plan and the signals still run; no side lock, so the 09:15 ⭐ row is added as usual. Pair "Auto at 09:15" is not affected (its own switch per card). Pause algo still blocks everything as before. Checked (simulated opening ticks, both apps): OFF → signal logged, no order; No trade today → the same; ON with yesterday's skip date → ordered; the Setup switch / checkbox save to settings.json and the Dashboard text updates, no page errors.

42. **Order Management: Pair and ⭐ on one page, glowing TRIGGERED cards (user, 26 Nov: all suggested; both apps).** The Pair and BEP Support ⭐ sub-pages are merged into **"Pair & ⭐"** (`/order-management/pair-star`, kind `pairstar`; the old `/order-management/pair` and `/bep-star` links open it; `pair_star_page`). Order Management now has three sub-pages: Same strike, Pair & ⭐, Manual Entry.
   - The Pair Add form stays at the top (⭐ cards are still added automatically; BEP cross cards come from BEP Pair cross).
   - **Filter chips** All / Pair / BEP cross / ⭐ with counts (`PS_FILTER`, `row_type`; default All, shared by every tab).
   - **Card order:** waiting for ⚡ (TRIGGERED / BLOCKED / ORDER FAILED) first, then ordered / open / pending, then WAITING, then FAILED / EXITED / CANCELLED; newest first inside each group (`card_rank`, this page only).
   - **Type tag** in each card header: ⭐ time (amber), BEP cross time (teal), **Pair** (blue-grey, new).
   - **Same option note:** a live ⭐ card and a live Pair card (fired leg) on the same strike + CE/PE both get an orange "Same option as a Pair card" / "Same option as a ⭐ card" tag (`same_option_notes`); the "option already open" confirm at ⚡ is unchanged.
   - One nav count (green when any card is TRIGGERED). Compact view: one table with a **Type** column (`pairstar_section`). Default targets stay per type (⭐ / Pair); Auto at 09:15 only on your own Pair cards; Delete per card. No logic changed: ⭐ still fails with its board row, Pair keeps the opponent rule / opponent SL.
   - **TRIGGERED cards glow (all Order Management pages):** a 2 px green border, a green background and a pulsing green shadow while the card waits for ⚡ (CSS `.om-trig`, keyframes `om-glow`); FAILED cards get a 2 px red border (`.om-fail`). Before: a thin 1 px green border that was hard to see.
   - Checked: both apps with sample ⭐ / Pair / BEP cross / failed ⭐ cards: nav, filter, order, tags, same-option note, compact table, old links, no page errors; BEP_Upstox unit tests pass.

## Session notes (26 Nov 2026, PRs #67–#73 here, #22–#28 in BEP_Upstox; read before continuing)
- **Merged (both apps unless noted):** #67 / U#22 GIFT Nifty chip in the header (decision 38 / U15) · #68 / U#23 Pair "Auto at 09:15" window until **09:30** (decision 37 note / U13) · #69 SL set after ⚡ checked on the live LTP every 2 s, "App SL" (decision 39, AlgoDelta only) · U#24 SL raised to / above the LTP exits at once + "SL MODIFY FAILED" alert (U16, BEP_Upstox only) · #70 / U#25 fired Pair card shows only the fired leg, bigger symbol (decision 40 / U17) · #71 / U#26 far-above-BEP warning checks the price the order buys at (decision 23 note: Limit / Stop-limit = the limit price, Strategy with an Entry Price = that price, plain Strategy = the LTP) · #72 / U#27 CLAUDE.md notes · #73 / U#28 **09:15 BEP order switch, OFF by default, + "No trade today"** (decision 41 / U18). Earlier the same morning: BEP_Upstox #21 partial exit (U14) and #20 / #66 notes.
- **Answered, nothing built:**
  - **09:15 BEP order and Pair "Auto at 09:15" run side by side** (both 09:15–09:20 / 09:30). The Pair auto order skips an option that already has an open / unfilled order (e.g. the 09:15 order). The 09:15 order does **not** check Pair orders, so both can buy the same option if the Pair is first (AlgoDelta: one `squareoff_position` closes both). Offered, not built: make the 09:15 order skip an option with an open order (suggested yes, both apps).
  - **Timeframe on an auto Pair row:** no effect during the auto window (live LTP every 2 s); it applies only after 09:30 when the row becomes a normal Pair.
  - **SL changed after ⚡ exited late (before #69):** it was checked only on 1-min candles from the minute after it was set; the dry-run exit was recorded at the SL level. Fixed by #69.
  - **Partial exit (BEP_Upstox only):** where it is and how to use it (Partial exit button on ordered cards / Order Details › Partial, 2+ lots).
- **09:15 order from tomorrow (27 Nov): the switch is OFF after the user pulls #73 / U#28.** No automatic 09:15 BEP order until the user turns it ON (Setup › 09:15 opening order); the Dashboard shows the signals as "not ordered". "No trade today" (option A) skips only that day's order; option B (block every new order today) was dropped because **Pause algo** already does that.
- **Open, waiting on the user:** a ⭐ 25900CE (entry 225.85, ⚡ 11:13:13) showed "12 POINT as sent" after a restart although the user had set "candle close below 219"; card EXITED · Manual at 220.75. Not reproduced: an SL set **after** ⚡ survives a reload (checked). Asked: was it set before ⚡ (on the TRIGGERED card) or after; was the 220.75 exit a manual square-off; and the `orders_2026-11-26.csv` row (`c_sl`) + the `common_watch_2026-11-26.json` row. If set before ⚡ and lost on the restart, look at saving / reloading watch rows.
- **Reminder set:** Sat 28 Nov 10:00 IST, a scheduled message into this chat to set up AWS Lightsail + host BEP_Upstox (`deploy/README.md`). Before then the user prepares an AWS account (card added) and a free Tailscale account.
- **Still to verify live:** GIFT Nifty key (Log line "GIFT NIFTY: instrument key …"; `(default; …)` or `GIFT NIFTY --` = send the Log line); Pair auto until 09:30 at a real open; App SL (#69); BEP_Upstox: an exchange refusing a SELL SL above the LTP (U#24), partial exit (U#21) in Sandbox / Live.
- **Pushing:** during market hours only on "push it and create the PRs" (the Stop hook's reminders don't override it); today the user also said "push everything and merge the PRs at once" for #71 / U#26. The user deletes the merged `claude/zen-einstein-n2mc3f` branch in both repos (Claude reminds them after each merge).

## Session notes (25 Nov 2026 afternoon / evening, PRs #63–#65 here, #18–#19 in BEP_Upstox; read before continuing)
- **Merged:** #63 the app-held Target for Strategy orders (decision 36, BEP-AlgoDelta only) · #64 Manual Entry Stop-limit form check (decision 28, also BEP_Upstox #18) · #65 Pair "Auto at 09:15" (decision 37, also BEP_Upstox #19, its decision 13). This notes PR is CLAUDE.md only.
- **Why #63:** the user raised a ⭐ order's Target from 30 to 100 pts after ⚡; it still exited at +30 because AlgoDelta held the sent target (no modify syntax). An SL change "worked" only because it was raised (tighter than AlgoDelta's). Option 2 chosen: the app holds every Order Management Strategy target (`is_tgt` false). Keep the PC on while those orders are open; the header badge says so.
- **Explained, nothing built:** a BUY Stop-limit needs its trigger **above** the LTP (it waits for a rise). To buy on a dip below the LTP use **Limit** (waits at the exchange) or **Price** (app-side PENDING ↓, then a market order). #64 now refuses a wrong trigger on the Manual Entry form instead of only at ⚡.
- **#65 for tomorrow's open (26 Nov):** add the Pair row before 09:15 with "Auto at 09:15" ON, Strategy or Limit (a Stop-limit is usually skipped: its default trigger is the leg's price, already crossed), set the card's Target / SL / Trail first; try it in Dry run. Watch the Log / toasts for "AUTO ORDER Pair … sent" or "NOT placed – …" and the AUTO chip. Not yet run in a real 09:15 open.
- **Still to test live (1 lot):** the app-held target (AlgoDelta should show **no target** on new Order Management Strategy orders; the app squares off at the target → EXITED · App target), plus the items under "Open / not yet verified".
- **Pushing:** after 15:30 the PRs were pushed directly; during market hours only when the user says "push it and create the PRs" (the Stop hook's push reminder doesn't override that). The work branch `claude/zen-einstein-n2mc3f` (both repos) was recreated from the default branch for each PR; the user deletes it after the merge.
- **Still open from earlier:** the 09:15 "LTP > open" question (see the 24–25 Nov notes); the "To port later" items in BEP_Upstox (second-side window, skip the first signal) wait for the user's test results.

## Session notes (24–25 Nov 2026, PRs #54–#62; read before continuing)
- **Merged in this session:** #54 09:15 second-side window (switch, 60 s; decision 32) · #56 Setup in bordered sections (decision 33) · #58 the 09:15 order's own trailing SL (decision 34) · #60 09:15 skip the first signal (decision 35) · #55 / #57 / #59 / #61 / #62 CLAUDE.md only. BEP_Upstox: #9 / #15 "To port later" notes, #11 Setup sections, #13 09:15 trailing SL, #10 / #12 / #14 / #16 / #17 CLAUDE.md only.
- **"Latest merge" line:** update it inside the next feature PR, not in a separate docs PR (user, 25 Nov).
- **Pushing during market hours:** the user allowed it case by case with "push it and create the PRs"; otherwise keep the commits local until after 15:30 (a Stop hook asks to push: the user's rule wins).
- **New defaults the user should know at the next 09:15 (all ON, Setup › 09:15 opening order):** skip the first signal, 60 s second-side window, 09:15 trailing SL 20 / 1 / 19. To test them one at a time, switch the others off. Watch the Log / Dashboard lines "1st signal skipped … waiting for the 2nd" and "restricted".
- **Open question, kept for later (user: "remain these things later today"):** "LTP > open" in the 09:15 rule. With BEP 150 and the open at 165 nothing can be ordered (LTP > 165 means ≥ BEP + 15, skipped). Offered: a Setup switch for "LTP > open" (enter at BEP + 2 while the candle is still red) or a higher max above BEP. Ask before building.
- **Answered, nothing built:**
  - **Trailing SL on ordered Strategy cards:** a trail ON at ⚡ is sent to AlgoDelta and can't be removed or changed afterwards (no modify syntax); the card's Remove only removes an app trail. The user will switch the trail OFF before ⚡ when they may want to change it. Offered, declined for now: label "AlgoDelta trail (can't change)" on those cards; an app-held trail switch for Strategy cards. In BEP_Upstox every trail is app-held and can be changed / removed while the order is open.
  - **Orders per second:** the 10 OPS line (SEBI retail algo rules, exchange threshold) counts **order messages** (new, and as understood modify / cancel), not lots; one 10-lot order = 1. The apps send well under 1 per second; bursts only on Square off all / 15:15 / several trails at once (~5 with the daily limit). No app-side rate limiter; an 8-per-second throttle was offered, not needed now. Confirm with Upstox (already on the question list).
  - **AlgoDelta paper trade on 25 Nov (25650CE, entry 142.75, exit 259.70, ₹7,601.75):** an entry-at-price card armed at 09:14 filled on the previous close (the stale pre-open LTP); the CE opened at 226.10, so a real order would not have filled. This app checks PENDING / limit / trail only while the market is open, so it can't take such a fill. Tip for the user: arm AlgoDelta price entries after 09:15.

## AlgoDelta JSON used
- Entry `strategy_order`: the template in `config._STRATEGY_ORDER`, with placeholders `{symbol}` (e.g. NIFTY23NOV2625400CE), `{qty}`, `{tgt}`, `{sl}`, `{is_trail}`, `{trail_*}`, `{exit_on_opposite}` and others.
- Limit entry: `{"type": "limit_order", "script_type": "CE", "script": "NIFTY23NOV2625200CE", "product": "INTRADAY", "quantity": 1, "price": 100, "transaction_type": "BUY"}` (quantity = lots).
- Stop-limit entry (PR #36): `{"type": "sl_order", "script_type": "CE", "script": "NIFTY23NOV2625650CE", "product": "INTRADAY", "quantity": 1, "price": 150, "trigger_price": 150, "transaction_type": "BUY"}` (quantity = lots; the app sends price = the limit, trigger_price = the trigger).
- Cancel: `{"type": "cancel_order", "script_type": "CE", "script": "NIFTY23NOV2625200CE", "product": "INTRADAY"}` (no order ID).
- Square-off: `{"type": "squareoff_position", "script_type": "CE", "script": "NIFTY23NOV2625300CE", "product": "INTRADAY"}`.
- AlgoDelta has **no modify-SL/Target syntax** (and no modify-order syntax) and no public read API (positions/fills), so live P&L comes from Upstox.

## Daily checklist (user)
1. Before 09:08: start the app. On Setup, enter today's Upstox token and upload the BEP CSV; the AlgoDelta settings are already saved.
2. AlgoDelta: the broker (Upstox) is logged in for the day and the **Trading** toggle is ON.
3. For live trading: the webhook is set, "I checked this JSON" is ticked and saved, Dry run is OFF and the header shows LIVE. Keep the PC awake from 09:08 to 09:20.
4. Add Order Management rows before 09:15 if you want first-candle triggers.

## Open / not yet verified
- **Not yet tested during market hours or against the real AlgoDelta webhook.** Test live with 1 lot first:
  - `market-quote/ohlc`, the pre-open index value, the `get-trades-for-day` fields and 3-min candles;
  - live option LTP on the cards (2 s), and a PENDING entry firing;
  - Entry and P&L filling in on cards;
  - a live square-off going SQUARING OFF → EXITED · Manual;
  - Manual Entry (Market and Price);
  - **Limit mode with 1 lot:** the order book fields/status names and the order matching, a fill → app SL square-off, `cancel_order` → CANCELLED, and what `cancel_order` does to other pending orders on the same option (does it also cancel a strategy order's SL/Target?);
  - per-card trailing as sent.
- **Waiting on the user:**
  - their own static IP (from their ISP, or an AWS Elastic IP / Azure static IP if hosted in the cloud) (for "Upstox direct" limit, modify, cancel and per-order square-off).
- **Branches:** the merged feature branches are deleted. Each cloud session has its own work branch (PRs #20 to #31: `claude/amazing-allen-klxor4`; PRs #32 to #49: `claude/affectionate-albattani-a69mce`; PR #40: `claude/manual-stoplimit-default`; PR #43: `claude/bep-distance-warning`; PRs #50 to #53: `claude/dazzling-keller-bxdbcj`; PRs #54 to #62: `claude/kind-knuth-vn2ga9`; PRs #63 to #74: `claude/zen-einstein-n2mc3f`; each time the same name in BEP_Upstox), recreated from `main` for each PR. The user deletes it after a merge.
- **NSE Circular 58/2026 (NSE/INSP/77559, 20 Nov 2026, effective immediately): Tech-savvy Retail Investors / Static IP.** The user shared it on 21 Nov 2026.
  - **What it says:**
    - Static IPs are **only** for "Tech-savvy Retail Investors" (retail clients who **develop their own algos using programming knowledge**, SEBI circular of 4 Feb 2025).
    - Algo providers giving static IPs to other retail clients is a violation. Brokers must take an **undertaking** from each tech-savvy client (own algos; **no recourse to the exchange grievance mechanism** for losses from the algo logic).
    - Penalties: brokers ₹5,000 per client (max ₹1 lakh, escalating); algo providers' **empanelment may be suspended or revoked**.
    - It repeats (NSE/INVG/69255, Annexure I, Para 14): a tech-savvy client must host the algo **"using a static IP at their end where Algo logic resides"**.
  - **Impact on this app:**
    - The user writes their own algo (this app), so they fit "tech-savvy" in substance.
    - But the static IP is **AlgoDelta's** (the ₹400/month add-on), not at the user's end. That's the model the circular targets.
    - AlgoDelta's future is **uncertain**: it may comply (undertakings via the broker), restrict or withdraw the static-IP add-on, or face suspension. Not legal advice.
  - **Decided / advised:**
    - **Setup C (cloud server with the user's own static IP + Upstox direct)** now also reduces regulatory and dependency risk, not only adds features. Phase 1 (cloud + AlgoDelta) may be skipped if the answers aren't clear.
    - Avoid new features that only work through AlgoDelta (e.g. relying on `cancel_order` / `limit_order` behaviour).
    - **Questions drafted** for the user to send (21 Nov 2026):
      - **AlgoDelta:** compliance and empanelment; will the static IP add-on continue (date, notice); is "algo on my PC + AlgoDelta's IP" accepted; who collects the undertaking; will webhooks keep working; algo ID / registration / order-per-second limit; refund; what happens to open positions and pending SL/Target if suspended.
      - **Upstox:** how to register as a tech-savvy retail client and the undertaking text; algo registration and the order-per-second threshold; registering a cloud static IP (AWS Elastic IP / Lightsail, Mumbai), how many and how to change; which order APIs are allowed (place/modify/cancel by ID, SL/SL-M, GTT, single-position exit); which calls don't need the IP; charges; rate limits; moving off the third-party platform; emergency exit if it stops.
    - **Waiting on the user:** the replies from AlgoDelta and Upstox. When they arrive, turn them into the cloud server + Upstox direct plan.
- **BEP Upstox: BUILT on 24 Nov 2026 in `ArunkumarEkambaram/BEP_Upstox`** (default branch `master`, port 8084, its own settings / orders files; its own CLAUDE.md has every decision). PRs 1–7 merged on 24 Nov:
  1. copy of this repo's `main` (with history) renamed "BEP Upstox", port 8084;
  2. a broker layer (`brokers/`: an interface like .NET dependency injection, so another broker can be added later; Upstox v3 orders; a paper broker for Dry run) and a Setup "Broker orders" card: mode **Dry run / Sandbox / Live**, market protection, sandbox token, Test order panel;
  3. **AlgoDelta removed there**: entry = market BUY; after the fill an **SL-M at the exchange**; trailing **modifies** it; target / candle SL / Pair opponent / square-off / 15:15 turn that SL into MARKET (one sell order, this order only); NO SL alert; "Order defaults" replaces the AlgoDelta settings, plus a max SL (17) for CANDLE-only SLs;
  4. Limit / Stop-limit as real LIMIT / SL BUY orders, partial fills, cancel by order ID (this order only);
  5. password login (30 days) and cloud scripts (`deploy/`: AWS Lightsail Mumbai, static IP, Tailscale, a systemd service, `update.sh`);
  6. NIFTY change % in the header (the same as PR #50 here);
  7. max loss per day, Dry run only, 09:15 exempt (the same as PR #52 here).
  - GTT was checked and kept for later (its trailing can't do decision 4's rule; not in the sandbox).
  - **Next (testing, no code):** Dry run on the PC on trading days (also the max loss in both apps: a low test limit, e.g. ₹100, to see the popup, the MAX LOSS badge and a BLOCKED PENDING card; Live use decided after that) → Sandbox (sandbox token) → set up the server together (Sat 28 – Sun 29 Nov) and register its static IP in Upstox after market hours → 1-lot live tests from 30 Nov → decide on Fri 11 Dec whether to switch or renew AlgoDelta for a month.
- *The plan as agreed on 23 Nov (kept for reference; built as above):*
- **PLANNED: a separate "BEP Upstox" app (Upstox direct + cloud), agreed 23 Nov 2026; start on 24 Nov (market holiday).** This app (AlgoDelta) stays unchanged and in use until BEP Upstox is proven live. **Target: switch before the AlgoDelta subscription ends (joined 15 Nov 2026, paid to about 14 Dec).**
  - **Estimate given (23 Nov):** about a quarter of the code changes (1,500–2,500 lines over 6–8 PRs). Unchanged: BEP Support, ⭐, Pair cross, Replay, Order Management triggers, exit rules, Order Details. Replaced: `order_bridge.py` → a new `upstox_orders.py` (place market / limit / SL, modify, cancel by order ID, exit a position, errors, rate limits). The biggest change is in `engine.py`: the app holds the SL / Target / trail itself instead of one `strategy_order`. `limit_orders.py` gets simpler (match by order ID). Square-off becomes per order. `app.py` Setup: the AlgoDelta section → Upstox order settings. Tokens: roughly 1 to 1.5× the PR #36–#45 session (about 3–6 M processed, mostly cached re-reads), spread over several sessions. Live 1-lot tests take the most time.
  - **Suggested answers (the user agreed to record them; confirm each before coding):**
    1. **New GitHub repo** (e.g. `BEP-Upstox`), a copy of `main` with its history. The user creates the empty repo (no README); Claude adds it with `add_repo` and pushes the copy. Important BEP-logic fixes are ported to both apps until one is retired. (Not chosen: one repo with two entry points.)
    2. **Side by side:** port **8084**, its own `settings.json`, orders files and logs; the same Upstox token works in both.
    3. **Phase 1 before the static IP:** the Upstox order module, dry run, the flow fill → SL order at the exchange → trailing by modifying that SL, and a Setup switch. Live orders need the registered static IP; check whether the Upstox order-API **sandbox** can test the calls without it.
    4. **SL at the exchange** (SL sell order right after the fill; trailing modifies it), so it stays active if the PC / app is down. **Target watched by the app** (at target: cancel the SL, then sell). No resting Target sell next to the SL sell (both could fill and leave a short). Ask Upstox whether GTT (entry + target + SL) supports trailing.
    5. **Cloud parts built now, deployed after the replies:** password login, deploy script (`git pull` + restart), run on boot, IST clock. Suggested provider: AWS Lightsail Mumbai (static IP included).
    6. **PR order (new repo):** (1) copy and rename (port 8084, own files, title "BEP Upstox"); (2) Upstox order module + dry run; (3) strategy orders with SL at the exchange + trailing; (4) Limit / Stop-limit / cancel / square-off by order ID; (5) login + cloud deploy script. Same working rules as here.
    7. **New question (added 23 Nov):** hold the SL as a **plain SL order that the app modifies to trail**, or as an **Upstox GTT order with ENTRY + TARGET + STOPLOSS legs** (broker-held, with a trailing gap; minimum 10 % of the LTP-to-SL distance). Check the GTT docs first (e.g. can the entry leg be a stop-limit, how the trailing gap compares to our trigger / gap rule), then suggest an answer. A broker-held SL is safer than the app placing it after the fill (the app could crash in between).
    - **Design:** keep the order code in its own module (cleaner to test). **Upstox only:** no broker switch and no Dhan work (the user's decision, 23 Nov).
  - **Timeline (agreed 23 Nov; aim for 14 Dec, but the date must not force an untested switch):**
    - **Tue 24 Nov (holiday):** the user creates the empty repo (no README) and asks Upstox about static-IP registration and the tech-savvy undertaking. Claude: confirm the 7 questions, then PR 1 (copy and rename) and PR 2 (order module + dry run).
    - **Wed 25 – Fri 27 Nov (evenings):** PR 3 (market entry → SL at the exchange → trailing by modify) and PR 4 (Limit / Stop-limit / cancel / square-off by order ID). The user runs Wednesday's AlgoDelta test, creates the cloud server (e.g. Lightsail Mumbai) and registers its IP in Upstox **after market hours**.
    - **Sat 28 – Sun 29 Nov:** PR 5 (login + deploy script) and the server set up together.
    - **Mon 30 Nov – Fri 4 Dec:** the new app on the cloud in **dry run** next to the AlgoDelta app, then **1-lot live tests** one at a time (entry, SL order, trail modify, cancel, exit, 15:15).
    - **Mon 7 – Fri 11 Dec:** small size live on BEP Upstox, with AlgoDelta as the backup.
    - **Fri 11 Dec: decide.** Switch, or renew AlgoDelta for one month (about ₹944) if the live tests aren't clean.
    - Scope until the switch: only move the existing features to Upstox direct; no new features. Phase 1 of the old plan (cloud + AlgoDelta) is skipped.
  - **Upstox static IP (checked 23 Nov):**
    - Required for place / modify / cancel / multi-order / GTT (error UDAPI1154 otherwise). Market data, candles, order book and trade book work without it (per a community guide).
    - Set in the Upstox developer site: My Apps → the app → Static IPs (primary required, secondary optional), or the API `PUT /user/ip`. **Saving invalidates the access token**: log in again, after market hours.
    - A third-party guide says the IP can be changed only **once a week** (not confirmed by Upstox): copy it carefully. Ask Upstox about the algo name / ID ("X-Algo-Name").
    - AlgoDelta uses its own IP; ask AlgoDelta to confirm that changing the user's Upstox app IP doesn't affect it.
  - **Broker comparison (reference only, 23 Nov; the user has Dhan, Upstox and AngelOne accounts but uses Upstox only):** Dhan's **Super Order** = entry + target + SL + trailing jump in one broker-held order (SL exit as market, no trailing SL-limit); Dhan trading APIs free, data APIs ₹499/month; static IP needed, locked 7 days. Upstox: trading + data APIs free, GTT with entry / target / SL legs and a trailing gap, about ₹20 per order. Not pursued.
  - **Wednesday 25 Nov tests on this app (1 lot):** the 09:15 max SL (AlgoDelta should show a 17-point SL, no trail), the BEP on the Manual Entry form, Target None, and the Stop-limit test moved from 24 Nov.
- **(Superseded by BEP Upstox above.) ON HOLD: cloud hosting / Upstox direct** (discussed 20 Nov 2026; the user wants the open bugs fixed first, then to come back to this; **priority raised by NSE Circular 58/2026**, see above):
  - **Today's cost:** AlgoDelta ₹400 + AlgoDelta static IP ₹400 + 18% GST ≈ **₹944/month**. Upstox needs a static IP for order APIs.
  - **Three setups compared:**
    - **A (today):** PC → AlgoDelta → Upstox.
    - **B:** the app on a cloud server, still through AlgoDelta. Gives uptime, almost no code change.
    - **C:** cloud + **Upstox direct** with the server's static IP (no AlgoDelta). Fastest. Real limit/modify/cancel by order ID, per-order square-off, SL at the exchange (SL-M/GTT). The biggest build and the most to maintain.
  - **Cloud cost estimates** (1 GB server, Mumbai/Bangalore, incl. 18% GST, ~₹85/$, check current prices):
    - AWS Lightsail ~₹500–600 (static IP included while attached);
    - DigitalOcean ~₹600–700;
    - AWS EC2 t3.micro + Elastic IP ~₹1,150–1,250;
    - Azure B1s + static IP ~₹1,200–1,300.
    - Upstox's API plan cost is to be checked by the user.
    - Saving against AlgoDelta is ~₹250–450/month; the real gain is features.
  - **Development stays the same in the cloud:** branch → PR → "merge PR #n" → on the server `git pull` + restart (a deploy script was offered).
  - **Effort:**
    - server setup is easy to moderate (1–2 h with guidance: Python, clone, run as a boot service, IST clock, login + HTTPS, register the static IP in the Upstox app);
    - the Upstox direct order module is the complicated part (place/modify/cancel by order ID, SL orders, trailing by modifying the SL, error handling, 1-lot live tests).
  - **Agreed plan (phased):**
    1. Cloud + keep AlgoDelta.
    2. Build Upstox direct **alongside** AlgoDelta, with a Setup switch "AlgoDelta / Upstox direct"; test with 1 lot.
    3. Drop AlgoDelta once direct is proven.
  - **Next step when resumed:** read the AlgoDelta / Upstox replies to the circular questions, then write up the questions for the cloud server and the Upstox direct module.
- **Ideas offered but not built:** a manual pre-open override; an AlgoDelta exit webhook for other features; "Modify price" for a limit (cancel + new limit; declined for now); the **Upstox WebSocket market feed** (prices pushed in real time instead of the 2 s polling; read-only, no static IP; medium effort, later).
