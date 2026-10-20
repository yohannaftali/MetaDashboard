# AGENTS.md — MetaDashboard

Profit calendar for several MT5 accounts (see `README.md` for use).

| File | What |
|---|---|
| `metadashboard.py` | Reads `.env`, fetches each account's deal history with the `MetaTrader5` package (investor password), computes the daily rows (`daily_rows`), writes `output/dashboard.html` from the template. `--demo` makes random accounts. |
| `dashboard_template.html` | The page: vanilla JS, no external resources; the data is injected in place of `/*__DATA__*/null`. Year / month views, account selector ("All accounts" when there are several), light / dark theme. |

Rules:
1. **Never point `MT5_TERMINAL_PATH` at a terminal that runs live EAs** and never run the script against the user's trading terminal: logging in switches that terminal's account. Test with `--demo`.
2. Investor (read-only) passwords only; never commit `.env`, `output/` or `data/` (balances, account numbers).
3. Daily % = trading P/L / balance at the day's first trade (`daily_rows`, tested with deposits before / after trades and withdrawal-only days); month / year / week % = P/L / balance at the start of the period's first trading day.
4. Commit / push only when the user asks; commit messages end with the `Co-Authored-By` line required by the session.
5. Check the page after changes: `python metadashboard.py --demo`, then a headless screenshot, e.g. `msedge --headless=new --screenshot=out.png --window-size=1400,1150 file:///.../output/dashboard.html` (append `#year` for the year view).
