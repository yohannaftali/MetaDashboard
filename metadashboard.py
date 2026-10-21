"""MetaDashboard: profit calendar for several MT5 accounts.

Reads the deal history of every account with its investor (read-only) password through the MetaTrader5
Python package, computes the daily trading P/L and its percentage of the start-of-day balance, and writes one
self-contained HTML calendar (year and month views) to output/dashboard.html.

    python metadashboard.py --serve    # local app on http://127.0.0.1:8765: add accounts, refresh, view
    python metadashboard.py            # fetch every account, write output/dashboard.html
    python metadashboard.py --demo     # random demo data, no MT5 needed
    python metadashboard.py --open     # also open the page in the browser

The terminal path and the accounts (login, server, investor password) are stored in data/metadashboard.db
(SQLite, passwords encrypted with Windows DPAPI) and are entered in the app's Settings. An existing .env is
imported once into an empty database. The terminal must be a terminal64.exe used only for monitoring:
logging in switches the account of that terminal, so never point it at a terminal that runs live EAs.
"""
import argparse
import datetime as dt
import json
import random
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from store import Store

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output'
CACHE = ROOT / 'data'
DB = CACHE / 'metadashboard.db'
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


def open_store(path):
    store = Store(path)
    env_path = ROOT / '.env'
    if not store.accounts() and env_path.exists():
        env = read_env(env_path)
        n = store.import_env(env, accounts_from_env(env))
        if n:
            print('imported %d account(s) from .env into %s (you can delete .env now)' % (n, path))
    return store


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


def demo_accounts(accounts=()):
    """Random history for the stored accounts (or two default ones when there are none)."""
    rnd = random.Random(7)
    specs = [(a['name'], a['login'], a['server']) for a in accounts] or [('Vantage', 0, 'demo'), ('Exness', 0, 'demo')]
    out = []
    for i, (name, login, server) in enumerate(specs):
        start, cur, risk = ((10000, 'USC', 1.0), (500, 'USD', 1.6))[i % 2]
        deals, t = [dict(time=dt.datetime(2025, 1, 2, 9), kind='balance', amount=start)], dt.date(2025, 1, 2)
        bal = start
        while t <= dt.date.today():
            if t.weekday() < 5 and rnd.random() < 0.8:
                pl = bal * rnd.gauss(0.18, 1.0) / 100 * risk
                deals.append(dict(time=dt.datetime.combine(t, dt.time(12, 30)), kind='trade', amount=pl, closes=rnd.randint(1, 3)))
                bal += pl
            t += dt.timedelta(days=1)
        out.append(dict(name=name + ' (demo)', login=login, server=server, currency=cur, balance=round(bal, 2),
                        equity=round(bal, 2), days=daily_rows(deals)))
    return out


def cache_file(acc):
    return CACHE / ('%d_%s.json' % (acc['login'], re.sub(r'[^A-Za-z0-9.-]+', '_', acc['server'])))


def load_cached(store, stale=()):
    """Last fetched data of the enabled accounts, without contacting MT5. stale: (login, server) of failed fetches."""
    out = []
    for acc in store.accounts(enabled_only=True):
        f = cache_file(acc)
        if f.exists():
            res = json.loads(f.read_text(encoding='utf-8'))
            res['name'] = acc['name']
            if (acc['login'], acc['server']) in stale:
                res['stale'] = True
            out.append(res)
    return out


def fetch_all(store, log=print):
    """Fetch every enabled account; an account that fails keeps its last good data, marked stale."""
    terminal = store.get('terminal_path')
    if not terminal or not Path(terminal).exists():
        raise RuntimeError('Set the MT5 terminal path (a terminal64.exe used only for monitoring) in Settings.')
    accounts = []
    CACHE.mkdir(exist_ok=True)
    for acc in store.accounts(with_password=True, enabled_only=True):
        cache = cache_file(acc)
        try:
            res = fetch_mt5(acc, terminal)
            cache.write_text(json.dumps(res), encoding='utf-8')
            log('%s %s: balance %.2f %s, %d days' % (acc['name'], acc['server'], res['balance'], res['currency'], len(res['days'])))
        except Exception as e:
            log('%s: FAILED: %s' % (acc['name'], e))
            if not cache.exists():
                continue
            res = json.loads(cache.read_text(encoding='utf-8'))
            res['stale'] = True
        accounts.append(res)
    return accounts


# --------------------------------------------------------------------------------------------- page
def render(accounts, app=False):
    data = dict(generated=dt.datetime.now().strftime('%Y-%m-%d %H:%M'), accounts=accounts, app=app)
    return TEMPLATE.read_text(encoding='utf-8').replace('/*__DATA__*/null', json.dumps(data, separators=(',', ':')))


def build(accounts, path):
    path.parent.mkdir(exist_ok=True)
    path.write_text(render(accounts), encoding='utf-8')
    return path


# --------------------------------------------------------------------------------------------- app
def serve(db_path, port, demo, open_browser):
    """Local app: the dashboard plus a JSON API to edit the store and refresh. Binds to 127.0.0.1 only."""
    store = open_store(db_path)
    lock = threading.Lock()  # one MT5 session at a time
    state = dict(stale=set())

    def page_accounts():
        # re-read on each load: picks up edits and fetches made by a scheduled run
        return demo_accounts(store.accounts(enabled_only=True)) if demo else load_cached(store, state['stale'])

    hosts = {'127.0.0.1:%d' % port, 'localhost:%d' % port}

    def config():
        return dict(terminal_path=store.get('terminal_path'), demo=demo, accounts=store.accounts())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, code, body, ctype='application/json'):
            raw = (body if isinstance(body, str) else json.dumps(body)).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype + '; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self, write):
            # Host check stops DNS rebinding; the custom header on writes makes other sites' requests need a
            # CORS preflight, which this server never grants.
            if self.headers.get('Host') not in hosts:
                return False
            return not write or self.headers.get('X-MetaDashboard') == '1'

        def body(self):
            n = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(n) or b'{}') if n else {}

        def do_GET(self):
            if not self.allowed(False):
                return self.send(403, {'error': 'forbidden'})
            if self.path in ('/', '/index.html') or self.path.startswith('/#'):
                return self.send(200, render(page_accounts(), app=True), 'text/html')
            if self.path == '/api/config':
                return self.send(200, config())
            self.send(404, {'error': 'not found'})

        def do_POST(self):
            if not self.allowed(True):
                return self.send(403, {'error': 'forbidden'})
            try:
                b = self.body()
                if self.path == '/api/terminal':
                    path = (b.get('terminal_path') or '').strip()
                    if path and not path.lower().endswith('terminal64.exe'):
                        raise ValueError('the path must end with terminal64.exe')
                    store.set('terminal_path', path)
                    return self.send(200, config())
                if self.path == '/api/accounts':
                    store.save_account(b.get('name'), b.get('login') or 0, b.get('server'), b.get('password'),
                                       bool(b.get('enabled', True)), b.get('id'))
                    return self.send(200, config())
                if self.path == '/api/accounts/delete':
                    store.delete_account(int(b['id']))
                    return self.send(200, config())
                if self.path == '/api/refresh':
                    lines, n = [], 0
                    if not demo:
                        with lock:
                            res = fetch_all(store, lines.append)
                        state['stale'] = {(r['login'], r['server']) for r in res if r.get('stale')}
                        n = len(res)
                    return self.send(200, dict(log=lines, count=n))
                self.send(404, {'error': 'not found'})
            except Exception as e:
                msg = 'an account with this login and server already exists' if 'UNIQUE' in str(e) else str(e)
                self.send(400, {'error': msg})

    httpd = HTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d/' % port
    print('MetaDashboard on %s  (database %s, Ctrl+C to stop)' % (url, db_path))
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--serve', action='store_true', help='run the local app (settings + dashboard) on 127.0.0.1')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--demo', action='store_true', help='random demo data, no MT5 needed')
    ap.add_argument('--open', action='store_true', help='open the page in the browser')
    ap.add_argument('--db', default=str(DB), help='SQLite database (default data/metadashboard.db)')
    ap.add_argument('--out', default=str(OUT / 'dashboard.html'))
    a = ap.parse_args()
    if a.serve:
        return serve(Path(a.db), a.port, a.demo, a.open)
    if a.demo:
        accounts = demo_accounts()
    else:
        try:
            accounts = fetch_all(open_store(Path(a.db)))
        except RuntimeError as e:
            sys.exit(str(e))
        if not accounts:
            sys.exit('No account data: add accounts with  python metadashboard.py --serve  (Settings).')
    out = build(accounts, Path(a.out))
    print('written', out)
    if a.open:
        webbrowser.open(out.as_uri())


if __name__ == '__main__':
    main()
