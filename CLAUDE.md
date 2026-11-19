# CLAUDE.md: BEP AlgoDelta project context (read at the start of every session)

Repo: `ArunkumarEkambaram/BEP-AlgoDelta` (branch `main`, latest merge = PR #10).
Run: `python app.py` → http://localhost:8083. Needs `nicegui>=3.1.0`, Python 3.14 on the user's PC.
Related repo (reference only, do not change): `ArunkumarEkambaram/LTP_Crossing`.

## Working rules agreed with the user
- **Always discuss requirements before writing code.** Ask questions with "Suggested:" answers and wait for the user's go-ahead.
- Work on a branch, open a PR, and merge **only when the user says "merge PR #n"**.
- During market hours, **don't push**. Keep work on a local branch until the user says so.
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
    - AlgoDelta `limit_order` (`{"type":"limit_order","script_type","script","product","quantity","price","transaction_type"}`) is kept for a later **Manual Entry** feature. It has no SL/Target fields, and no cancel syntax is known yet.
  - **Order Details**
  - **Setup**
  - **Logs**
- `bep_monitor.py`: BEP Support board, ⭐ first support, and the 09:15 opening order (prepare + 1 s tick).
- `common_watch.py`: Order Management rows (Same strike, Pair, ⭐).
- `order_bridge.py`: AlgoDelta JSON (`strategy_order`) and `squareoff_position`.
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

## AlgoDelta JSON used
- Entry `strategy_order`: the template in `config._STRATEGY_ORDER`, with placeholders `{symbol}` (e.g. NIFTY23NOV2625400CE), `{qty}`, `{tgt}`, `{sl}`, `{is_trail}`, `{trail_*}`, `{exit_on_opposite}` and others.
- Square-off: `{"type": "squareoff_position", "script_type": "CE", "script": "NIFTY23NOV2625300CE", "product": "INTRADAY"}`.
- AlgoDelta has **no modify-SL/Target syntax** and no public read API (positions/fills), so live P&L comes from Upstox.

## Daily checklist (user)
1. Before 09:08: start the app. On Setup, enter today's Upstox token and upload the BEP CSV; the AlgoDelta settings are already saved.
2. AlgoDelta: the broker (Upstox) is logged in for the day and the **Trading** toggle is ON.
3. For live trading: the webhook is set, "I checked this JSON" is ticked and saved, Dry run is OFF and the header shows LIVE. Keep the PC awake from 09:08 to 09:20.
4. Add Order Management rows before 09:15 if you want first-candle triggers.

## Open / not yet verified
- Not yet tested during market hours or against the real AlgoDelta webhook: `market-quote/ohlc`, the pre-open index value, `get-trades-for-day` fields, and 3-min candles. Test live with quantity 1 first.
- Merged branches are still on GitHub: `claude/dry-run-exit`, `claude/first-candle-fifo`, `claude/order-mgmt-sections`, `claude/pair-watch`, `claude/per-order-sl-target`, `claude/per-type-targets`. Delete them with:
  `git push origin --delete claude/dry-run-exit claude/first-candle-fifo claude/order-mgmt-sections claude/pair-watch claude/per-order-sl-target claude/per-type-targets`
- **Per-card Trailing SL (PR #15):**
  - Click the card's Trailing box to open a popup: ON/OFF, Type, Trigger, Point and Gap. It starts from Setup and is stored as `c_trail` (`engine.row_trail`).
  - It's sent in that card's JSON (and simulated in dry run) and locks once ordered. It's not available with a CANDLE SL (`is_sl` false).
  - Ordered cards show the Target, SL and Trail **as sent** (from the order JSON).
  - Start/End time was dropped (the user doesn't want it).
- **Manual square-off (PR #16):**
  - **Where:** a **Square off** button on ordered cards (Order Management) and in the Action column of Order Details (every open order, including the 09:15 one). Order Details also has **Square off all** (one `squareoff_position` per option).
  - **Confirm popup:** shows the quantity, entry, LTP and approximate P&L. AlgoDelta's `squareoff_position` has **no order ID or quantity**, so it closes the **whole position on that script**. The popup lists the other open orders on the same option, and all of them are marked.
  - **Placing a second order on an option that's already open** asks for confirmation first (option A; there's no hard block).
  - **Not blocked** by Pause algo or the daily limit.
  - **Live:** `sq` = `SENT hh:mm:ss`, the card shows SQUARING OFF, and the trade book is refreshed at once. Exit/P&L then come from Upstox, and the card shows EXITED · Manual. On failure: `FAILED`, with a **Retry square off** button.
  - **Dry run:** Exit = a fresh LTP at the click.
  - **After a square-off:** pair opponent exits and app-watched CANDLE/custom rules are skipped (`engine.squared_off`).
  - **Saved:** `sq` is stored in the orders file.
  - **Verified by the user:** AlgoDelta's square-off closes the position, including its pending SL/Target.
- **Target fix (PR #15):** rows no longer copy the Setup target when they're added (the old `_stamp_target`). The default Target is read from Setup **when the order is placed**, so a Setup change applies to existing rows too.
- Ideas offered but not built: a manual pre-open override; an AlgoDelta exit webhook for other features; per-order trailing for the 09:15 order (it uses Setup).
