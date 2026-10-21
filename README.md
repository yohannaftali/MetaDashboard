# Meta Dashboard

Profit calendar for several MetaTrader 5 accounts: daily, monthly and yearly profit in **% of the balance**. Two tabs: **Calendar** (Year: 12 small months; Month: a big calendar with the day's %, P/L and closed trades, plus week totals; Day: the day hour by hour from 00:00 to 23:00 server time, like an agenda, its numbers in the cards) and **Chart** (every account side by side for the day, month or year: one bar each with its %, plus a table). Under the tabs pick **Day / Month / Year**, step with ‹ ›, click the date for a calendar, or press **Today**. Not an EA: a [Flet](https://flet.dev) desktop app reads each account's deal history with its **investor (read-only) password**. A command-line fetch also writes one self-contained page, `output/dashboard.html`.

## Install (Windows)

Paste this into PowerShell (Start menu → type `powershell` → Enter):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex; & ~\.local\bin\uv.exe tool install --force --reinstall-package metadashboard https://github.com/yohannaftali/MetaDashboard/archive/refs/heads/main.zip; & ~\.local\bin\metadashboard.exe --install-shortcuts"
```

It installs [uv](https://docs.astral.sh/uv/) (with uv's official installer), then MetaDashboard with its own Python and packages (nothing system-wide), and adds a **MetaDashboard** shortcut to the Start menu and the desktop. Run the same line again to update (close MetaDashboard first: Windows locks the files of a running app). The first start downloads the Flet window client once and can take a minute.

To uninstall: `metadashboard --remove-shortcuts`, then `uv tool uninstall metadashboard`. Your settings stay in `%LOCALAPPDATA%\MetaDashboard`; delete that folder to remove them too.

From a clone instead: install uv, then `uv run metadashboard` in the folder. A clone keeps `data/`, `output/` and `mt5/` in its own folder.

## Setup

You need MetaTrader 5 installed (from your broker or [metatrader5.com](https://www.metatrader5.com)). Open **MetaDashboard → Settings**:

1. **Create monitoring terminal.** MetaDashboard copies your MetaTrader 5 into its own folder (`%LOCALAPPDATA%\MetaDashboard\mt5`), with the broker servers your MetaTrader knows. It logs in to your accounts there, because a login switches the terminal's account: your own MetaTrader, and the EAs running in it, are never started or changed, and its saved logins are not copied.
2. **Log in to accounts.** The monitoring terminal opens. Log in once to each account (*File → Login to Trade Account*) with its **investor (read-only) password** and **Save password** ticked. Close the terminal.
3. That's it: MetaDashboard finds the accounts you logged in to and fetches them. **Find accounts** looks again later, e.g. after logging in to another account.

The terminal keeps the passwords (that's what *Save password* does); MetaDashboard only stores the list of accounts. For an account the terminal cannot log in to by itself, add it by hand under *Add account* with its investor password: that one is stored encrypted with Windows DPAPI (readable only by your Windows user on this PC) and never shown again.

The settings live in `data/metadashboard.db` (SQLite; installed: `%LOCALAPPDATA%\MetaDashboard\data`). An existing `.env` (see `.env.example`) is imported once into an empty database; delete `.env` afterwards. An existing monitoring terminal (e.g. a copy in `C:\MT5-Monitor`, started once with `/portable`) can be entered instead in Settings.

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
- **All accounts**: amounts are added up, cent accounts (USC, EUC) converted to their dollar / euro (÷ 100). A week / month / year % is taken on the sum of every account's own balance at its first trading day in that period (a day's % on the accounts that traded that day).
- **Count from** (Settings → Edit account, optional): only the history from that date counts, everywhere (Calendar, Chart, totals, the HTML page). Use it for an old account that traded another strategy before; the full history stays cached, so the date can be changed or cleared later.
- **History download.** Right after the first login to an account, MT5 still downloads its history; a fetch waits until the deal count stays the same (up to 45 s), and an account with a balance but no deals yet is marked stale instead of being saved empty.
- **Max equity DD** (risk): the equity is rebuilt like MT5's own report: every minute a position is open, the positions of a symbol are valued at the worse of that minute's M1 low and high and added to the balance. The drawdown is the deepest fall below the equity's high in the period; deposits and withdrawals do not count. All accounts: the deepest single account. An approximation (per minute, profit linear in the price).
- Open positions (floating P/L) are not in the calendar's P/L; the cards show the current balance and equity.

`output/` and `data/` contain balances, account numbers and the encrypted passwords and are not committed (`.gitignore`).

## License

[MIT](LICENSE)
