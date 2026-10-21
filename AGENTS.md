# AGENTS.md — MetaDashboard

Profit calendar for several MT5 accounts (see `README.md` for use).

| File | What |
|---|---|
| `pyproject.toml` | uv project, `flet[desktop]==0.86.4` (same as `flet/senar`, `tools/release_manager`); scripts `metadashboard` (app) and `metadashboard-fetch` (core). |
| `src/metadashboard/app.py` | Flet desktop app (`uv run metadashboard`, `--demo`, `--web`, `--db`): header (account, Year / Month, period, Refresh, Settings, theme), cards, year / month calendar, Settings dialog. Ports the page's numbers (`combined_days`, `period`, `day_pct`). Refresh runs `fetch_all` in a thread; auto refresh every `refresh_minutes` (settings table, 0 = off, min 5) without error dialogs. |
| `src/metadashboard/core.py` | Reads the accounts from the store, fetches each account's deal history with the `MetaTrader5` package (investor password), computes the daily rows (`daily_rows`), caches them in `data/`, writes `output/dashboard.html` from the template (`uv run metadashboard-fetch`). `--demo` makes random accounts. |
| `src/metadashboard/terminal.py` | `Terminal` context for `fetch_all` (Windows, ctypes): starts the monitoring terminal minimized (`/portable`), re-minimizes after each login, closes it with `WM_CLOSE` after the fetch (kill after 20 s); a terminal already running is left alone. |
| `src/metadashboard/store.py` | SQLite store `data/metadashboard.db`: terminal path + accounts; investor passwords DPAPI-encrypted, never returned by the API. A `.env` is imported once into an empty store. |
| `src/metadashboard/dashboard_template.html` | The static page: vanilla JS, no external resources; the data is injected in place of `/*__DATA__*/null`. Year / month views, account selector ("All accounts" when there are several), light / dark theme. |

Rules:
1. **Never point the terminal path (Settings / `MT5_TERMINAL_PATH`) at a terminal that runs live EAs** and never run the script against the user's trading terminal: logging in switches that terminal's account. Test with `--demo`.
2. Investor (read-only) passwords only; never commit `.env`, `output/` or `data/` (balances, account numbers, the database).
3. Daily % = trading P/L / balance at the day's first trade (`daily_rows`, tested with deposits before / after trades and withdrawal-only days); month / year / week % = P/L / balance at the start of the period's first trading day.
4. Commit / push only when the user asks; commit messages end with the `Co-Authored-By` line required by the session.
5. Check after changes: the app with `uv run metadashboard --demo --db <scratch>.db` (a screenshot via `page.take_screenshot()` with `page.enable_screenshots = True`); the page with `uv run metadashboard-fetch --demo`, then a headless screenshot, e.g. `msedge --headless=new --screenshot=out.png --window-size=1400,1150 file:///.../output/dashboard.html` (append `#year` for the year view).
