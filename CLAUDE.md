# CLAUDE.md: BEP AlgoDelta project context (read at the start of every session)

Repo: `ArunkumarEkambaram/BEP-AlgoDelta` (branch `main`, latest merge = PR #29; updated together with each feature PR).
Run: `python app.py` → http://localhost:8083. Needs `nicegui>=3.1.0`, Python 3.14 on the user's PC.
Related repo (reference only, do not change): `ArunkumarEkambaram/LTP_Crossing`.

## Working rules agreed with the user
- **Always discuss requirements before writing code.** Ask questions with "Suggested:" answers and wait for the user's go-ahead.
- Work on a branch, open a PR, and merge **only when the user says "merge PR #n"**. This applies to **every** change, docs-only ones included (no direct pushes to `main`; confirmed again after PR #17).
- During market hours, **don't push**. Keep work on a local branch until the user says so.
- **Never change `main` directly** (no commits, pushes or merges to it on Claude's own initiative), especially near or during market hours. Every change, docs-only ones included, goes to a **new branch**. It's merged later, only when the user says "merge PR #n". The user's running app stays on the `main` it pulled. (Asked on 20 Nov 2026, just before the open. The user can allow an exception in chat, as for PR #23.)
- After merging, the user runs `git pull origin main` and restarts the app.
- `__pycache__/`, `settings.json`, `upstox_token.json`, `orders_*.csv` and `common_watch_*.json` are git-ignored. Never commit them.
- The cloud session can't delete GitHub branches (proxy 403). The user deletes merged branches, or turns on "Automatically delete head branches".

## Architecture (after PR #3)
- `engine.py`: **one background engine** for the whole app (`app.timer`). It handles the Upstox connection, scans, the 09:15 order, Order Management, orders, tracking, log and alerts. Pages only read its state; version counters trigger redraws, and events trigger toasts and browser notifications in every tab.
- `app.py`: NiceGUI **single-page app** (`ui.sub_pages`), dark theme with a toggle, a header (LTP, status, Upstox ✓, DRY RUN/LIVE, Pause alerts, Pause algo) and a left nav. The pages are:
  - **Dashboard**
  - **BEP Support**
  - **Order Management**: a nav group with three sub-pages, each with its own Add form and list. They are `/order-management/same-strike`, `/order-management/pair` and `/order-management/bep-star`; `/order-management` opens Same strike. Each sub-item shows a row count, and its badge is green when a row is triggered and waiting for Place order. Add a sub-page through `OM_SUB` in `app.py`. Each row is an **order card** (like AlgoDelta's): a header with symbol/Buy/INTRADAY/TF, a status chip (WAITING, TRIGGERED, ORDERED · SENT/DRY RUN, EXITED, FAILED) and ⚡ Place / ✕ Delete / ✏ Edit (WAITING only). The body shows Entry Price, Quantity (lots, editable per card until ordered), P&L, live LTP, Entry level, Target, Stoploss and Trailing (per card, PR #15). A "Compact view" switch brings back the table. Live option LTP comes from `engine.refresh_option_ltps` (one batched call every `OPTION_LTP_SECONDS` = 2 s). Each card is linked to its order through `order_id`, which supplies Entry and P&L. **Entry at a price (PR C):**
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
6. **Order Details:** Entry, Exit, LTP, Captured Points (**Exit − Entry, shown only once exited**) and P&L ₹.
   - **Live:** Upstox trade book (`get-trades-for-day`, every 30 s). Fills are matched by option and **shared FIFO between orders on the same option** (PR #10).
   - **Dry run:** entry = LTP at the signal. The exit is **simulated** from 1-min candles using the order's SL/Target/trail (SL first if both hit in the same minute; 15:15 square-off). It's saved in the orders file.
   - The JSON column is hidden in the table but kept in the file and the CSV/XLSX downloads.
7. **Order Management** (manual trades: alert, then **Place order**; nothing automatic). The page has three sections:
   - **Same strike:** strike, Leg (Both/CE/PE), common price, timeframe 3/5 min. Fires when a close crosses above the price (previous close at or below it), **once**. A later close below turns the row red, with no alert. Rows added pre-open use the **first candle's open** as the previous price, so the earliest trigger is 09:20 / 09:18 (PR #10).
   - **Pair (CE vs PE):** CE strike, PE strike, common price (optional separate PE price), buffer (default 1).
     - **Entry, either side:** a leg closes above its price while the opponent closes below price − buffer. The leg must have been at or below its price first ("armed").
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
   - **Form:** Strike, CE/PE, Lots, **Price / Market** and Entry price (pre-filled with the live LTP from `engine.quote_option`).
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
   - **Order Details:** shows the limit state and app rules in SL/Target, plus a Cancel order action. The SL/Target can't be edited after placing (`order_rule_editable` is false).

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

## AlgoDelta JSON used
- Entry `strategy_order`: the template in `config._STRATEGY_ORDER`, with placeholders `{symbol}` (e.g. NIFTY23NOV2625400CE), `{qty}`, `{tgt}`, `{sl}`, `{is_trail}`, `{trail_*}`, `{exit_on_opposite}` and others.
- Limit entry: `{"type": "limit_order", "script_type": "CE", "script": "NIFTY23NOV2625200CE", "product": "INTRADAY", "quantity": 1, "price": 100, "transaction_type": "BUY"}` (quantity = lots).
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
- **Branches:** the merged feature branches are deleted. Each cloud session has its own work branch (PRs #20 to #29: `claude/amazing-allen-klxor4`), recreated from `main` for each PR. The user deletes it after a merge.
- **ON HOLD: cloud hosting / Upstox direct** (discussed 20 Nov 2026; the user wants the open bugs fixed first, then to come back to this):
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
  - **Next step when resumed:** write up the questions for Phase 1 (cloud hosting) or the Upstox direct module, as the user chooses.
- **Ideas offered but not built:** a manual pre-open override; an AlgoDelta exit webhook for other features; per-order trailing for the 09:15 order (it uses Setup); "Modify price" for a limit (cancel + new limit; declined for now); the **Upstox WebSocket market feed** (prices pushed in real time instead of the 2 s polling; read-only, no static IP; medium effort, later).
