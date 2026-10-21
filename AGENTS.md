# AGENTS.md — MetaDashboard

Profit calendar for several MT5 accounts (see `README.md` for use).

| File | What |
|---|---|
| `metadashboard.py` | Reads the accounts from the store, fetches each account's deal history with the `MetaTrader5` package (investor password), computes the daily rows (`daily_rows`), writes `output/dashboard.html` from the template. `--demo` makes random accounts. `--serve` runs the local app (127.0.0.1, JSON API under `/api/`, writes need the `X-MetaDashboard: 1` header). |
| `store.py` | SQLite store `data/metadashboard.db`: terminal path + accounts; investor passwords DPAPI-encrypted, never returned by the API. A `.env` is imported once into an empty store. |
| `dashboard_template.html` | The page: vanilla JS, no external resources; the data is injected in place of `/*__DATA__*/null`. Year / month views, account selector ("All accounts" when there are several), light / dark theme; Settings dialog and Refresh when `DATA.app` (served). |

Rules:
1. **Never point the terminal path (Settings / `MT5_TERMINAL_PATH`) at a terminal that runs live EAs** and never run the script against the user's trading terminal: logging in switches that terminal's account. Test with `--demo`.
2. Investor (read-only) passwords only; never commit `.env`, `output/` or `data/` (balances, account numbers, the database).
3. Daily % = trading P/L / balance at the day's first trade (`daily_rows`, tested with deposits before / after trades and withdrawal-only days); month / year / week % = P/L / balance at the start of the period's first trading day.
4. Commit / push only when the user asks; commit messages end with the `Co-Authored-By` line required by the session.
5. Check the page after changes: `python metadashboard.py --demo` (or `--serve --demo --db <scratch>.db` for the app), then a headless screenshot, e.g. `msedge --headless=new --screenshot=out.png --window-size=1400,1150 file:///.../output/dashboard.html` (append `#year` for the year view).
