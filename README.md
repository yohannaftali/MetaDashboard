# MetaDashboard

Profit calendar for several MetaTrader 5 accounts: daily, monthly and yearly profit in **% of the balance**, in a year view (12 small months) and a month view (big calendar with the day's %, P/L and closed trades, plus week totals). Not an EA: a Python script reads each account's deal history with its **investor (read-only) password** and writes one self-contained page, `output/dashboard.html`.

## Setup

1. `pip install -r requirements.txt` (the `MetaTrader5` package, Windows only).
2. **A terminal for monitoring only.** The `MetaTrader5` package logs in by switching the account of the terminal it uses, so it must not be the terminal that runs your EAs.
   - Copy the folder `C:\Program Files\MetaTrader 5` to e.g. `C:\MT5-Monitor`.
   - Start `C:\MT5-Monitor\terminal64.exe /portable` once, and add each broker through *File → Open an Account* (type the broker name), so the terminal knows the servers (`Vantage...`, `Exness...`). Close it.
3. Copy `.env.example` to `.env` and fill in `MT5_TERMINAL_PATH` and one block per account (`PREFIX_MT5_LOGIN`, `PREFIX_MT5_SERVER`, `PREFIX_MT5_INVESTOR_PASSWORD`, optional `PREFIX_NAME`). Any prefix works; add as many accounts as you like.

## Use

```
python metadashboard.py --open     # fetch all accounts, write and open output/dashboard.html
python metadashboard.py            # fetch and write only
python metadashboard.py --demo     # demo data, no MT5 needed
```

Open `output/dashboard.html#year` to start in the year view. To keep it current, run the script from Windows Task Scheduler (e.g. every hour) and refresh the page. If one account cannot be fetched, its last good data (in `data/`) is shown and marked as stale.

## How the numbers are computed

- **Daily P/L** = profit + swap + commission (+ fees) of the day's buy / sell deals, by **server date**. Deposits, withdrawals, credit and bonuses are not profit.
- **Daily %** = daily P/L / the balance when the day's first trade happens (a deposit made earlier that day counts, one made later does not).
- **Month / year %** = the period's P/L / the balance at the start of its first trading day. Week totals the same way.
- **All accounts**: amounts are added up, cent accounts (USC, EUC) converted to their dollar / euro (÷ 100), and the % is taken on the added balances.
- Open positions (floating P/L) are not in the calendar; the cards show the current balance and equity.

`output/` and `data/` contain balances and account numbers and are not committed (`.gitignore`).
