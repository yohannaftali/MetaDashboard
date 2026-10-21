# MetaDashboard

Profit calendar for several MetaTrader 5 accounts: daily, monthly and yearly profit in **% of the balance**, in a year view (12 small months) and a month view (big calendar with the day's %, P/L and closed trades, plus week totals). Not an EA: a [Flet](https://flet.dev) desktop app reads each account's deal history with its **investor (read-only) password**. A command-line fetch also writes one self-contained page, `output/dashboard.html`.

## Setup

1. Install [uv](https://docs.astral.sh/uv/). The first `uv run` creates `.venv` and installs Flet 0.86.4 (same version as `flet/senar` and `tools/release_manager`) and the `MetaTrader5` package (Windows only); Python 3.11+.
2. **A terminal for monitoring only.** The `MetaTrader5` package logs in by switching the account of the terminal it uses, so it must not be the terminal that runs your EAs.
   - Copy the folder `C:\Program Files\MetaTrader 5` to e.g. `C:\MT5-Monitor`.
   - Start `C:\MT5-Monitor\terminal64.exe /portable` once, and add each broker through *File → Open an Account* (type the broker name), so the terminal knows the servers (`Vantage...`, `Exness...`). Close it.
3. Start the app: `uv run metadashboard` (opens a desktop window). In **Settings** enter the monitoring terminal path (e.g. `C:\MT5-Monitor\terminal64.exe`) and add each account (name, login, server, investor password), then press **Refresh**.

The settings live in `data/metadashboard.db` (SQLite). Investor passwords are encrypted with Windows DPAPI (readable only by your Windows user on this PC) and are never shown again. An existing `.env` (see `.env.example`) is imported once into an empty database; delete `.env` afterwards.

## Use

```
uv run metadashboard                     # desktop app: settings, refresh, calendar
uv run metadashboard --demo              # the app with demo data, no MT5 needed
uv run metadashboard --web               # the app in the browser instead of a window
uv run metadashboard-fetch --open        # fetch all accounts, write and open output/dashboard.html
uv run metadashboard-fetch               # fetch and write only (e.g. from Task Scheduler)
uv run metadashboard-fetch --demo        # demo page, no MT5 needed
```

In the HTML page, open `#year` to start in the year view.

**Keeping the data current.** Data changes only when a fetch runs. In the app, press **Refresh** or set **Auto refresh** in Settings (every N minutes while the app is open, at least 5, 0 = off). Without the app open, run `uv run --directory <this folder> metadashboard-fetch` from Windows Task Scheduler (e.g. every hour); the app shows that data when it starts and after each Refresh. Use one of the two, not both at the same time: they share the monitoring terminal.

**The terminal during a fetch.** One monitoring terminal serves every account: each is logged in to in turn. For a fetch, the terminal is started minimized (without taking the focus), kept minimized after each login, and closed normally when all accounts are read. If that terminal is already open (started by hand), it is used as it is and left open. If one account cannot be fetched, its last good data (in `data/`) is shown and marked as stale.

## How the numbers are computed

- **Daily P/L** = profit + swap + commission (+ fees) of the day's buy / sell deals, by **server date**. Deposits, withdrawals, credit and bonuses are not profit.
- **Daily %** = daily P/L / the balance when the day's first trade happens (a deposit made earlier that day counts, one made later does not).
- **Month / year %** = the period's P/L / the balance at the start of its first trading day. Week totals the same way.
- **All accounts**: amounts are added up, cent accounts (USC, EUC) converted to their dollar / euro (÷ 100), and the % is taken on the added balances.
- Open positions (floating P/L) are not in the calendar; the cards show the current balance and equity.

`output/` and `data/` contain balances, account numbers and the encrypted passwords and are not committed (`.gitignore`).
