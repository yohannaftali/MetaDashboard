"""MetaDashboard: profit calendar for several MT5 accounts.

Reads the deal history of every account in .env with its investor (read-only) password through the
MetaTrader5 Python package, computes the daily trading P/L and its percentage of the start-of-day balance,
and writes one self-contained HTML calendar (year and month views) to output/dashboard.html.

    python metadashboard.py            # fetch every account, write output/dashboard.html
    python metadashboard.py --demo     # random demo accounts, no MT5 needed
    python metadashboard.py --open     # also open the page in the browser

Accounts in .env: any PREFIX with PREFIX_MT5_LOGIN, PREFIX_MT5_SERVER and PREFIX_MT5_INVESTOR_PASSWORD
(e.g. VANTAGE_..., EXNESS_...). MT5_TERMINAL_PATH must point to a terminal64.exe used only for monitoring:
logging in switches the account of that terminal, so never point it at a terminal that runs live EAs.
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
CACHE = ROOT / 'data'
TEMPLATE = ROOT / 'dashboard_template.html'


# --------------------------------------------------------------------------------------------- config
def read_env(path):
    env = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$', line)
            if m and not line.lstrip().startswith('#'):
                env[m[1]] = m[2].strip('"').strip("'")
    return env


def accounts_from_env(env):
    accounts = []
    for key in sorted(env):
        m = re.match(r'^([A-Z0-9]+)_MT5_LOGIN$', key)
        if not m:
            continue
        p = m[1]
        server, password = env.get(p + '_MT5_SERVER'), env.get(p + '_MT5_INVESTOR_PASSWORD')
        if not (env[key] and server and password):
            print('skip %s: login, server or investor password missing' % p)
            continue
        accounts.append(dict(name=env.get(p + '_NAME', p.title()), login=int(env[key]), server=server, password=password))
    return accounts


# --------------------------------------------------------------------------------------------- data
def server_time(ts):
    # MT5 deal times are server time encoded as seconds since 1970; read them without a time-zone shift
    return dt.datetime(1970, 1, 1) + dt.timedelta(seconds=ts)


def daily_rows(deals):
    """deals: list of dict(time=datetime (server), kind='trade'|'balance', amount=float)
    Returns {date: dict(pl, deposit, start, trades)}: start = the balance when the day's first trade closes or
    opens (so a deposit made earlier that day counts, one made later does not); on a day without trades the
    balance at the end of the day's deposits / withdrawals."""
    deals = sorted(deals, key=lambda d: d['time'])
    days, balance = {}, 0.0
    for d in deals:
        day = d['time'].date().isoformat()
        row = days.setdefault(day, dict(pl=0.0, deposit=0.0, start=None, trades=0))
        if d['kind'] == 'balance':
            row['deposit'] += d['amount']
        else:
            if row['start'] is None:
                row['start'] = balance
            row['pl'] += d['amount']
            row['trades'] += d.get('closes', 0)
        balance += d['amount']
        if d['kind'] == 'balance' and row['trades'] == 0 and row['pl'] == 0:
            row['_end'] = balance
    for row in days.values():
        end = row.pop('_end', 0.0)
        if row['start'] is None:
            row['start'] = end
    return {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in days.items()}


def fetch_mt5(acc, terminal):
    import MetaTrader5 as mt5
    if not mt5.initialize(path=terminal, login=acc['login'], password=acc['password'], server=acc['server'],
                          portable=True, timeout=60000):
        raise RuntimeError('MT5 login failed for %s: %s' % (acc['name'], mt5.last_error()))
    try:
        info = mt5.account_info()
        raw = mt5.history_deals_get(dt.datetime(2000, 1, 1), dt.datetime.now() + dt.timedelta(days=2)) or []
        deals = []
        for d in raw:
            amount = d.profit + d.swap + d.commission + getattr(d, 'fee', 0.0)
            if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                closes = 1 if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT, mt5.DEAL_ENTRY_OUT_BY) else 0
                deals.append(dict(time=server_time(d.time), kind='trade', amount=amount, closes=closes))
            else:  # balance, credit, bonus, correction, ... : money moved, not trading
                deals.append(dict(time=server_time(d.time), kind='balance', amount=amount))
        return dict(name=acc['name'], login=acc['login'], server=acc['server'], currency=info.currency,
                    balance=info.balance, equity=info.equity, days=daily_rows(deals))
    finally:
        mt5.shutdown()


def demo_accounts():
    rnd = random.Random(7)
    out = []
    for name, start, cur, risk in (('Vantage', 10000, 'USC', 1.0), ('Exness', 500, 'USD', 1.6)):
        deals, t = [dict(time=dt.datetime(2025, 1, 2, 9), kind='balance', amount=start)], dt.date(2025, 1, 2)
        bal = start
        while t <= dt.date.today():
            if t.weekday() < 5 and rnd.random() < 0.8:
                pl = bal * rnd.gauss(0.18, 1.0) / 100 * risk
                deals.append(dict(time=dt.datetime.combine(t, dt.time(12, 30)), kind='trade', amount=pl, closes=rnd.randint(1, 3)))
                bal += pl
            t += dt.timedelta(days=1)
        out.append(dict(name=name + ' (demo)', login=0, server='demo', currency=cur, balance=round(bal, 2),
                        equity=round(bal, 2), days=daily_rows(deals)))
    return out


# --------------------------------------------------------------------------------------------- page
def build(accounts, path):
    data = dict(generated=dt.datetime.now().strftime('%Y-%m-%d %H:%M'), accounts=accounts)
    html = TEMPLATE.read_text(encoding='utf-8').replace('/*__DATA__*/null', json.dumps(data, separators=(',', ':')))
    path.parent.mkdir(exist_ok=True)
    path.write_text(html, encoding='utf-8')
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--demo', action='store_true', help='random demo accounts, no MT5 needed')
    ap.add_argument('--open', action='store_true', help='open the page in the browser')
    ap.add_argument('--out', default=str(OUT / 'dashboard.html'))
    a = ap.parse_args()
    if a.demo:
        accounts = demo_accounts()
    else:
        env = read_env(ROOT / '.env')
        terminal = env.get('MT5_TERMINAL_PATH')
        if not terminal or not Path(terminal).exists():
            sys.exit('Set MT5_TERMINAL_PATH in .env to a terminal64.exe used only for monitoring (see README).')
        accounts = []
        CACHE.mkdir(exist_ok=True)
        for acc in accounts_from_env(env):
            cache = CACHE / ('%s_%d.json' % (acc['name'], acc['login']))
            try:
                res = fetch_mt5(acc, terminal)
                cache.write_text(json.dumps(res), encoding='utf-8')
                print('%-12s %s  balance %.2f %s, %d days' % (acc['name'], acc['server'], res['balance'], res['currency'], len(res['days'])))
            except Exception as e:  # keep the last good data of that account
                print('%-12s FAILED: %s' % (acc['name'], e))
                if not cache.exists():
                    continue
                res = json.loads(cache.read_text(encoding='utf-8'))
                res['stale'] = True
            accounts.append(res)
        if not accounts:
            sys.exit('No account data (check .env).')
    out = build(accounts, Path(a.out))
    print('written', out)
    if a.open:
        webbrowser.open(out.as_uri())


if __name__ == '__main__':
    main()
