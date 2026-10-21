# MetaDashboard

Profit calendar for several MetaTrader 5 accounts: daily, monthly and yearly profit in **% of the balance**, in a year view (12 small months) and a month view (big calendar with the day's %, P/L and closed trades, plus week totals). Not an EA: a [Flet](https://flet.dev) desktop app reads each account's deal history with its **investor (read-only) password**. A command-line fetch also writes one self-contained page, `output/dashboard.html`.

## Install (Windows)

1. Install [uv](https://docs.astral.sh/uv/) (skip if you have it), in PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Then open a **new** PowerShell window, so `uv` is on your `PATH`.
2. Install MetaDashboard and add its Start menu and desktop shortcuts:

   ```powershell
   uv tool install https://github.com/yohannaftali/MetaDashboard/archive/refs/heads/main.zip
   metadashboard --install-shortcuts
   ```

uv installs MetaDashboard with its own Python and packages (nothing system-wide) and puts `metadashboard` and `metadashboard-fetch` on your `PATH`. Settings and data are kept in `%LOCALAPPDATA%\MetaDashboard`. The first start downloads the Flet window client once and can take a minute.

- **Update:** `uv tool install --force --reinstall-package metadashboard https://github.com/yohannaftali/MetaDashboard/archive/refs/heads/main.zip`
- **Uninstall:** `metadashboard --remove-shortcuts`, then `uv tool uninstall metadashboard`. This keeps `%LOCALAPPDATA%\MetaDashboard` (your accounts, with encrypted investor passwords, and the fetched history); delete it to remove those too.

From a clone instead: install uv, then `uv run metadashboard` in the folder. The first `uv run` creates `.venv` with Flet 0.86.4 and the `MetaTrader5` package (Windows only); Python 3.11+. A clone keeps `data/` and `output/` in its own folder.

## Setup

1. Install (above).
2. Set up a **terminal for monitoring only** (below).
3. Start **MetaDashboard** from the Start menu (or `metadashboard`; `uv run metadashboard` in a clone). In **Settings** enter the monitoring terminal path (e.g. `C:\MT5-Monitor\terminal64.exe`) and add each account (name, login, server, investor password), then press **Refresh**.

### The monitoring terminal

MetaDashboard logs in to your accounts one after another through an MT5 terminal, and each login switches that terminal's account. So it needs **its own copy of MetaTrader 5**, never the terminal that runs your EAs or that you trade with. One copy serves all your accounts, also from different brokers.

1. **Copy MetaTrader 5 to its own folder.** In PowerShell:

   ```powershell
   robocopy "C:\Program Files\MetaTrader 5" "C:\MT5-Monitor" /E
   ```

   Or in File Explorer: copy the folder `C:\Program Files\MetaTrader 5` and paste it as `C:\MT5-Monitor`. If your MT5 came from a broker, its folder may have another name, e.g. `C:\Program Files\Vantage International MetaTrader 5`; copy that one. Any MT5 copy works for every broker.
2. **Start the copy once in portable mode**, so it keeps its data in its own folder and not in the one of your trading terminal:

   ```powershell
   & "C:\MT5-Monitor\terminal64.exe" /portable
   ```
3. **Add each broker's server.** In that terminal: *File → Open an Account*, type the broker name (e.g. `Vantage`, `Exness`), pick the server of your account (e.g. `VantageInternational-Live 3`) and log in once with the account's **investor password**. Repeat for every broker. You don't need to keep these logins: MetaDashboard logs in itself.
4. **Close the terminal.** MetaDashboard starts it minimized for each fetch and closes it afterwards.
5. In MetaDashboard → **Settings**, enter `C:\MT5-Monitor\terminal64.exe` as the terminal path and press **Save**.

The settings live in `data/metadashboard.db` (SQLite; installed: `%LOCALAPPDATA%\MetaDashboard\data`). Investor passwords are encrypted with Windows DPAPI (readable only by your Windows user on this PC) and are never shown again. An existing `.env` (see `.env.example`) is imported once into an empty database; delete `.env` afterwards.

## Use

Installed, run these without `uv run` (e.g. `metadashboard --demo`). In a clone:

```
uv run metadashboard                     # desktop app: settings, refresh, calendar
uv run metadashboard --demo              # the app with demo data, no MT5 needed
uv run metadashboard --web               # the app in the browser instead of a window
uv run metadashboard-fetch --open        # fetch all accounts, write and open output/dashboard.html
uv run metadashboard-fetch               # fetch and write only (e.g. from Task Scheduler)
uv run metadashboard-fetch --demo        # demo page, no MT5 needed
```

In the HTML page, open `#year` to start in the year view.

**Keeping the data current.** Data changes only when a fetch runs. In the app, press **Refresh** or set **Auto refresh** in Settings (every N minutes while the app is open, at least 5, 0 = off). Without the app open, run `metadashboard-fetch` (in a clone: `uv run --directory <this folder> metadashboard-fetch`) from Windows Task Scheduler (e.g. every hour); the app shows that data when it starts and after each Refresh. Use one of the two, not both at the same time: they share the monitoring terminal.

**The terminal during a fetch.** One monitoring terminal serves every account: each is logged in to in turn. For a fetch, the terminal is started minimized (without taking the focus), kept minimized after each login, and closed normally when all accounts are read. If that terminal is already open (started by hand), it is used as it is and left open. If one account cannot be fetched, its last good data (in `data/`) is shown and marked as stale.

## How the numbers are computed

- **Daily P/L** = profit + swap + commission (+ fees) of the day's buy / sell deals, by **server date**. Deposits, withdrawals, credit and bonuses are not profit.
- **Daily %** = daily P/L / the balance when the day's first trade happens (a deposit made earlier that day counts, one made later does not).
- **Month / year %** = the period's P/L / the balance at the start of its first trading day. Week totals the same way.
- **All accounts**: amounts are added up, cent accounts (USC, EUC) converted to their dollar / euro (÷ 100), and the % is taken on the added balances.
- Open positions (floating P/L) are not in the calendar; the cards show the current balance and equity.

`output/` and `data/` contain balances, account numbers and the encrypted passwords and are not committed (`.gitignore`).

## License

[MIT](LICENSE)
