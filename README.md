# MetaDashboard

Profit calendar for several MetaTrader 5 accounts: daily, monthly and yearly profit in **% of the balance**, in a year view (12 small months) and a month view (big calendar with the day's %, P/L and closed trades, plus week totals). Not an EA: a Python script reads each account's deal history with its **investor (read-only) password** and writes one self-contained page, `output/dashboard.html`.

## Setup

1. `pip install -r requirements.txt` (the `MetaTrader5` package, Windows only).
2. **A terminal for monitoring only.** The `MetaTrader5` package logs in by switching the account of the terminal it uses, so it must not be the terminal that runs your EAs.
   - Copy the folder `C:\Program Files\MetaTrader 5` to e.g. `C:\MT5-Monitor`.
   - Start `C:\MT5-Monitor\terminal64.exe /portable` once, and add each broker through *File → Open an Account* (type the broker name), so the terminal knows the servers (`Vantage...`, `Exness...`). Close it.
3. Start the app: `python metadashboard.py --serve --open` (opens http://127.0.0.1:8765). In **Settings** enter the monitoring terminal path (e.g. `C:\MT5-Monitor\terminal64.exe`) and add each account (name, login, server, investor password), then press **Refresh**.

The settings live in `data/metadashboard.db` (SQLite). Investor passwords are encrypted with Windows DPAPI (readable only by your Windows user on this PC) and are never sent back to the browser. An existing `.env` (see `.env.example`) is imported once into an empty database; delete `.env` afterwards.

## Use

```
python metadashboard.py --serve --open   # local app: settings, refresh, calendar (127.0.0.1 only)
python metadashboard.py --open           # fetch all accounts, write and open output/dashboard.html
python metadashboard.py                  # fetch and write only (e.g. from Task Scheduler)
python metadashboard.py --demo           # demo data, no MT5 needed (add --serve to try the app)
```

Open `#year` to start in the year view, `#settings` to open the settings. To keep the data current without pressing Refresh, run `python metadashboard.py` from Windows Task Scheduler (e.g. every hour); the app shows the latest fetched data on each page load. If one account cannot be fetched, its last good data (in `data/`) is shown and marked as stale.

## How the numbers are computed

- **Daily P/L** = profit + swap + commission (+ fees) of the day's buy / sell deals, by **server date**. Deposits, withdrawals, credit and bonuses are not profit.
- **Daily %** = daily P/L / the balance when the day's first trade happens (a deposit made earlier that day counts, one made later does not).
- **Month / year %** = the period's P/L / the balance at the start of its first trading day. Week totals the same way.
- **All accounts**: amounts are added up, cent accounts (USC, EUC) converted to their dollar / euro (÷ 100), and the % is taken on the added balances.
- Open positions (floating P/L) are not in the calendar; the cards show the current balance and equity.

`output/` and `data/` contain balances, account numbers and the encrypted passwords and are not committed (`.gitignore`).
