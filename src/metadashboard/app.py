"""MetaDashboard desktop app (Flet): profit calendar for several MT5 accounts, with settings and refresh.

    uv run metadashboard           # the app: shows the data last fetched, Refresh fetches every account
    uv run metadashboard --demo    # random demo data, no MT5 needed
    uv run metadashboard --web     # open it in the browser instead of a window

Same numbers as the HTML page written by core.py: daily % = trading P/L / balance at the day's first trade,
month / year / week % = P/L / balance at the start of the period's first trading day.
"""
import argparse
import asyncio
import calendar
import datetime as dt
import threading
import time
from pathlib import Path

import flet as ft

from .core import DB, demo_accounts, fetch_all, load_cached, open_store

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']
DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
# amounts of cent accounts are converted to their dollar for the combined view
RATE = {'USC': 0.01, 'EUC': 0.01, 'GBX': 0.01}
BASE = {'USC': 'USD', 'EUC': 'EUR', 'GBX': 'GBP'}
LIGHT = dict(bg='#f6f7f9', panel='#ffffff', text='#1d2330', muted='#6b7280', line='#e3e6ea', pos='#16a34a',
             neg='#dc2626', accent='#2563eb', weekend='#f0f2f5')
DARK = dict(bg='#0f1218', panel='#171b23', text='#e6e8ec', muted='#8b93a1', line='#262c37', pos='#22c55e',
            neg='#f85149', accent='#60a5fa', weekend='#1b2029')
NARROW = 720
MIN_AUTO_REFRESH = 5  # minutes; a fetch logs in to every account in turn


# --------------------------------------------------------------------------------------------- numbers
def combined_days(accounts, key):
    """{date: dict(pl, start, deposit, trades)} in the account currency, or added up in dollars for 'all'."""
    if key != 'all':
        return accounts[int(key)]['days']
    out = {}
    for a in accounts:
        r = RATE.get(a['currency'], 1)
        for d, v in a['days'].items():
            o = out.setdefault(d, dict(pl=0.0, start=0.0, deposit=0.0, trades=0))
            o['pl'] += v['pl'] * r
            o['start'] += v['start'] * r
            o['deposit'] += v['deposit'] * r
            o['trades'] += v['trades']
    return out


def currency(accounts, key):
    if key != 'all':
        return accounts[int(key)]['currency']
    found = {BASE.get(a['currency'], a['currency']) for a in accounts}
    return found.pop() if len(found) == 1 else 'mixed'


def period(days, frm, to):
    """P/L of the period and its % of the balance at the start of the period's first trading day."""
    pl, start, up, down, trades = 0.0, None, 0, 0, 0
    for d in sorted(days):
        if not frm <= d <= to:
            continue
        v = days[d]
        if start is None and v['start'] > 0:
            start = v['start']
        pl += v['pl']
        trades += v['trades']
        up += v['pl'] > 0
        down += v['pl'] < 0
    return dict(pl=pl, pct=pl / start * 100 if start else None, up=up, down=down, trades=trades)


def day_pct(v):
    return v['pl'] / v['start'] * 100 if v and v['start'] > 0 else None


def iso(y, m, d):
    return '%d-%02d-%02d' % (y, m + 1, d)


def fmt_pct(p):
    return '' if p is None else ('+' if p > 0 else '') + '%.2f%%' % p


def fmt_amt(a, cur):
    return ('+' if a > 0 else '') + '{:,.2f}'.format(a) + (' ' + cur if cur and cur != 'mixed' else '')


# --------------------------------------------------------------------------------------------- app
class App:
    def __init__(self, page, store, demo):
        self.page, self.store, self.demo = page, store, demo
        self.lock = threading.Lock()  # one MT5 session at a time
        self.stale = set()
        today = dt.date.today()
        self.acc, self.view, self.y, self.m = 'all', 'month', today.year, today.month - 1
        self.dark = page.platform_brightness == ft.Brightness.DARK
        self.narrow = False
        self.busy = False
        page.title = 'Profit Calendar'
        page.padding = 0
        page.spacing = 0
        page.theme = ft.Theme(color_scheme_seed=LIGHT['accent'])
        page.dark_theme = ft.Theme(color_scheme_seed=DARK['accent'])
        page.on_resize = self.on_resize
        self.last_refresh = time.monotonic()
        self.load()
        self.render()
        page.run_task(self.auto_refresh)
        if not self.store.accounts():
            self.open_settings()

    def minutes(self):
        """Auto refresh interval from Settings, 0 = off."""
        try:
            return max(0, int(self.store.get('refresh_minutes', '0') or 0))
        except ValueError:
            return 0

    async def auto_refresh(self):
        while True:
            await asyncio.sleep(20)
            n = self.minutes()
            if n and not self.busy and time.monotonic() - self.last_refresh >= n * 60:
                self.on_refresh(auto=True)

    def load(self):
        # re-read on each load: picks up edits and fetches made by a scheduled metadashboard-fetch
        self.loaded = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
        if self.demo:
            self.accounts = demo_accounts(self.store.accounts(enabled_only=True))
        else:
            self.accounts = load_cached(self.store, self.stale)
        keys = self.keys()
        if self.acc not in keys:
            self.acc = keys[0] if keys else 'all'

    def keys(self):
        return (['all'] if len(self.accounts) > 1 else []) + [str(i) for i in range(len(self.accounts))]

    # ------------------------------------------------------------------ layout
    def render(self):
        self.C = DARK if self.dark else LIGHT
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        self.page.bgcolor = self.C['bg']
        body = ft.Column([self.cards(), self.calendar(), self.note()] if self.accounts else [self.empty()],
                         spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)
        self.page.controls.clear()
        self.page.controls.extend([self.header(), ft.Container(body, padding=16, expand=True)])
        self.page.update()

    def text(self, value, size=14, color=None, weight=None, **kw):
        return ft.Text(value, size=size, color=color or self.C['text'], weight=weight, **kw)

    def box(self, content, **kw):
        kw.setdefault('bgcolor', self.C['panel'])
        kw.setdefault('border', ft.Border.all(1, self.C['line']))
        kw.setdefault('border_radius', 12)
        kw.setdefault('padding', ft.Padding.symmetric(vertical=10, horizontal=12))
        return ft.Container(content, **kw)

    def header(self):
        C, items = self.C, [self.text('Profit Calendar', 18, weight=ft.FontWeight.BOLD)]
        if self.accounts:
            names = {'all': 'All accounts'}
            for i, a in enumerate(self.accounts):
                names[str(i)] = '%s%s (%s)' % (a['name'], ' · %s' % a['login'] if a['login'] else '', a['currency'])
            items += [
                ft.Dropdown(value=self.acc, options=[ft.DropdownOption(key=k, text=names[k]) for k in self.keys()],
                            on_select=self.on_account, dense=True, width=300),
                ft.SegmentedButton(segments=[ft.Segment('year', label=ft.Text('Year')),
                                             ft.Segment('month', label=ft.Text('Month'))],
                                   selected=[self.view], show_selected_icon=False, on_change=self.on_view),
                ft.Row([ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip='Previous', on_click=lambda e: self.step(-1)),
                        self.text(str(self.y) if self.view == 'year' else '%s %d' % (MONTHS[self.m], self.y),
                                  weight=ft.FontWeight.W_600, width=130, text_align=ft.TextAlign.CENTER),
                        ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip='Next', on_click=lambda e: self.step(1))],
                       spacing=0, tight=True),
                ft.OutlinedButton('Today', on_click=self.on_today),
            ]
        items += [
            ft.Container(expand=True),
            ft.OutlinedButton('Refreshing…' if self.busy else 'Refresh', icon=ft.Icons.REFRESH, disabled=self.busy,
                              on_click=self.on_refresh),
            ft.OutlinedButton('Settings', icon=ft.Icons.SETTINGS, on_click=lambda e: self.open_settings()),
            ft.IconButton(ft.Icons.LIGHT_MODE if self.dark else ft.Icons.DARK_MODE, tooltip='Theme',
                          on_click=self.on_theme),
        ]
        return ft.Container(ft.Row(items, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                            bgcolor=C['panel'], padding=ft.Padding.symmetric(vertical=12, horizontal=16),
                            border=ft.Border.only(bottom=ft.BorderSide(1, C['line'])))

    def empty(self):
        return self.box(self.text('No account data yet. Open Settings to add the MT5 terminal and your accounts, '
                                  'then press Refresh.', color=self.C['muted'], text_align=ft.TextAlign.CENTER),
                        padding=32, alignment=ft.Alignment.CENTER)

    def bounds(self):
        if self.view == 'year':
            return iso(self.y, 0, 1), iso(self.y, 11, 31)
        return iso(self.y, self.m, 1), iso(self.y, self.m, 31)

    def cards(self):
        C, D, cur = self.C, combined_days(self.accounts, self.acc), currency(self.accounts, self.acc)
        P = period(D, *self.bounds())
        accs = self.accounts if self.acc == 'all' else [self.accounts[int(self.acc)]]
        rate = lambda a: RATE.get(a['currency'], 1) if self.acc == 'all' else 1
        bal = sum(a['balance'] * rate(a) for a in accs)
        eq = sum(a['equity'] * rate(a) for a in accs)
        money = lambda v: '{:,.2f}'.format(v) + (' ' + cur if cur != 'mixed' else '')
        label = 'Year' if self.view == 'year' else 'Month'
        sign = self.sign_color(P['pl'])
        cards = [('Balance', money(bal), None), ('Equity', money(eq), None),
                 (label + ' P/L', fmt_amt(P['pl'], cur), sign), (label + ' %', fmt_pct(P['pct']) or '-', sign),
                 ('Winning / losing days', '%d / %d' % (P['up'], P['down']), None),
                 ('Closed trades', str(P['trades']), None)]
        return ft.ResponsiveRow([
            self.box(ft.Column([self.text(k, 12, C['muted']), self.text(v, 16 if self.narrow else 20, c, ft.FontWeight.W_600)],
                               spacing=2), col={'xs': 6, 'md': 4, 'lg': 2})
            for k, v, c in cards], spacing=12, run_spacing=12)

    def sign_color(self, v):
        return self.C['pos'] if v > 0 else self.C['neg'] if v < 0 else None

    def shade(self, pct, cap):
        """(background, white text) of a day: green / red, stronger for a bigger % of the period's biggest day."""
        if not pct:
            return None, False
        a = min(1, abs(pct) / cap) * 0.75 + 0.12
        return ft.Colors.with_opacity(round(a, 2), self.C['pos'] if pct > 0 else self.C['neg']), a > 0.5

    def calendar(self):
        D = combined_days(self.accounts, self.acc)
        frm, to = self.bounds()
        cap = max([1] + [abs(day_pct(v) or 0) for d, v in D.items() if frm <= d <= to])
        cur = currency(self.accounts, self.acc)
        return self.year_view(D, cap, cur) if self.view == 'year' else self.month_view(D, cap, cur)

    def year_view(self, D, cap, cur):
        C, today, months = self.C, dt.date.today().isoformat(), []
        for m in range(12):
            M = period(D, iso(self.y, m, 1), iso(self.y, m, 31))
            first, n = calendar.monthrange(self.y, m + 1)
            cells = [ft.Container(expand=True) for _ in range(first)]
            for d in range(1, n + 1):
                k = iso(self.y, m, d)
                v, wk = D.get(k), (first + d - 1) % 7 >= 5
                p = day_pct(v)
                bg, white = self.shade(p, cap)
                cells.append(ft.Container(
                    self.text(str(d), 10, '#ffffff' if white else C['muted']), expand=True, aspect_ratio=1,
                    alignment=ft.Alignment.CENTER,
                    bgcolor=bg or (C['weekend'] if wk else None), border_radius=4,
                    border=ft.Border.all(2, C['accent']) if k == today else None,
                    tooltip='%s: %s (%s)' % (k, fmt_amt(v['pl'], cur), fmt_pct(p)) if v else k))
            cells += [ft.Container(expand=True) for _ in range(-len(cells) % 7)]
            grid = [ft.Row([ft.Container(self.text(h[0], 10, C['muted']), expand=True, alignment=ft.Alignment.CENTER)
                            for h in DOW], spacing=3)]
            grid += [ft.Row(cells[i:i + 7], spacing=3) for i in range(0, len(cells), 7)]
            title = ft.Row([self.text(MONTHS[m], weight=ft.FontWeight.W_600),
                            self.text(fmt_pct(M['pct']), color=self.sign_color(M['pl']), weight=ft.FontWeight.W_600)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            months.append(self.box(ft.Column([title] + grid, spacing=3), col={'xs': 12, 'sm': 6, 'md': 4, 'xl': 3},
                                   on_click=lambda e, m=m: self.open_month(m), ink=False))
        return ft.ResponsiveRow(months, spacing=12, run_spacing=12)

    def month_view(self, D, cap, cur):
        C, today = self.C, dt.date.today().isoformat()
        first_day = dt.date(self.y, self.m + 1, 1)
        start = first_day - dt.timedelta(days=first_day.weekday())
        last = first_day.replace(day=calendar.monthrange(self.y, self.m + 1)[1])
        week_col = not self.narrow
        head = [ft.Container(self.text(d, 12, C['muted']), expand=10, alignment=ft.Alignment.CENTER) for d in DOW]
        if week_col:
            head.append(ft.Container(self.text('Week', 12, C['muted']), expand=9, alignment=ft.Alignment.CENTER))
        rows = [ft.Row(head, spacing=6)]
        height, w = 64 if self.narrow else 92, 0
        while True:
            cells, wpl, wstart = [], 0.0, None
            for i in range(7):
                day = start + dt.timedelta(days=w * 7 + i)
                k, in_month = day.isoformat(), day.month == self.m + 1
                v = D.get(k)
                p = day_pct(v)
                if v and in_month:
                    wpl += v['pl']
                    if wstart is None and v['start'] > 0:
                        wstart = v['start']
                bg, white = self.shade(p, cap) if in_month else (None, False)
                fg = '#ffffff' if white else None
                sub = fg or C['muted']
                lines = [self.text(str(day.day), 12, sub), ft.Container(expand=True)]
                if v and in_month:
                    lines.append(self.text(fmt_pct(p), 13 if self.narrow else 18, fg, ft.FontWeight.W_600))
                    if not self.narrow:
                        lines.append(self.text(fmt_amt(v['pl'], cur), 12, sub))
                        lines.append(self.text('%d trade%s' % (v['trades'], 's' if v['trades'] > 1 else '')
                                               if v['trades'] else '', 12, sub))
                tip = None
                if v:
                    tip = 'start balance %.2f' % v['start'] + (', deposit/withdrawal %.2f' % v['deposit'] if v['deposit'] else '')
                cells.append(ft.Container(
                    ft.Column(lines, spacing=0), expand=10, height=height, border_radius=10,
                    padding=ft.Padding.symmetric(vertical=6, horizontal=4 if self.narrow else 8),
                    bgcolor=bg or (C['weekend'] if i >= 5 else C['panel']), opacity=1 if in_month else 0.35,
                    border=ft.Border.all(2, C['accent']) if k == today else ft.Border.all(1, C['line']),
                    tooltip=tip))
            if week_col:
                lines = [self.text('W%d' % (w + 1), 12, C['muted']), ft.Container(expand=True)]
                if wstart:
                    lines += [self.text(fmt_pct(wpl / wstart * 100), 18, self.sign_color(wpl), ft.FontWeight.W_600),
                              self.text(fmt_amt(wpl, cur), 12, C['muted'])]
                cells.append(ft.Container(ft.Column(lines, spacing=0), expand=9, height=height, border_radius=10,
                                          padding=ft.Padding.symmetric(vertical=6, horizontal=8),
                                          border=ft.Border.all(1, C['line'])))
            rows.append(ft.Row(cells, spacing=3 if self.narrow else 6))
            w += 1
            if start + dt.timedelta(days=w * 7) > last:
                break
        return ft.Column(rows, spacing=3 if self.narrow else 6)

    def note(self):
        stale = [a['name'] for a in self.accounts if a.get('stale')]
        spans = [ft.TextSpan(
            'Loaded %s. Daily %% = trading P/L (profit + swap + commission) / balance when the day\'s first trade '
            'happens; deposits and withdrawals are not profit. Month / year %% = P/L / balance at the start of the '
            'period. Server dates.' % self.loaded
            + (' All accounts: cent accounts converted to their dollar.' if self.acc == 'all' and len(self.accounts) > 1 else '')
            + (' Auto refresh every %d min.' % self.minutes() if self.minutes() else ''))]
        if stale:
            spans.append(ft.TextSpan(' Last fetch failed, older data shown: %s.' % ', '.join(stale),
                                     ft.TextStyle(color=self.C['neg'])))
        return ft.Text(spans=spans, size=12, color=self.C['muted'])

    # ------------------------------------------------------------------ events
    def on_resize(self, e):
        narrow = (self.page.width or 1400) < NARROW
        if narrow != self.narrow:
            self.narrow = narrow
            self.render()

    def on_account(self, e):
        self.acc = e.control.value
        self.render()

    def on_view(self, e):
        self.view = e.control.selected[0] if e.control.selected else self.view
        self.render()

    def open_month(self, m):
        self.m, self.view = m, 'month'
        self.render()

    def step(self, d):
        if self.view == 'year':
            self.y += d
        else:
            self.y, self.m = divmod(self.y * 12 + self.m + d, 12)
        self.render()

    def on_today(self, e):
        t = dt.date.today()
        self.y, self.m = t.year, t.month - 1
        self.render()

    def on_theme(self, e):
        self.dark = not self.dark
        self.render()

    def on_refresh(self, e=None, auto=False):
        if self.busy:
            return
        self.busy = True
        self.render()
        self.page.run_thread(self.refresh, auto)

    def refresh(self, auto=False):
        """Fetch every account. A failed auto refresh only marks the accounts stale (no dialog every N minutes)."""
        lines, error = [], None
        try:
            if not self.demo:
                with self.lock:
                    res = fetch_all(self.store, lines.append)
                self.stale = {(r['login'], r['server']) for r in res if r.get('stale')}
        except Exception as e:
            error = str(e)
        self.busy = False
        self.last_refresh = time.monotonic()
        self.load()
        self.render()
        if auto:
            print('\n'.join(['auto refresh %s' % dt.datetime.now().strftime('%H:%M')] + lines + ([error] if error else [])))
        elif error or any('FAILED' in l for l in lines):
            self.page.show_dialog(ft.AlertDialog(title=ft.Text('Refresh'), content=ft.Text(error or '\n'.join(lines)),
                                                 actions=[ft.TextButton('OK', on_click=lambda e: self.page.pop_dialog())]))

    # ------------------------------------------------------------------ settings
    def open_settings(self):
        Settings(self).open()


class Settings:
    """Settings dialog: the monitoring terminal path and the accounts. Investor passwords are write-only."""

    def __init__(self, app):
        self.app, self.store, self.page = app, app.store, app.page
        self.editing, self.changed = None, False
        self.term = ft.TextField(label='terminal64.exe path', value=self.store.get('terminal_path'),
                                 hint_text=r'C:\MT5-Monitor\terminal64.exe', dense=True, expand=True)
        self.auto = ft.TextField(label='Auto refresh, minutes (0 = off)', value=str(app.minutes()), dense=True,
                                 width=260, keyboard_type=ft.KeyboardType.NUMBER,
                                 input_filter=ft.NumbersOnlyInputFilter())
        self.rows = ft.Column(spacing=0)
        self.name = ft.TextField(label='Name', hint_text='Vantage', dense=True, expand=True)
        self.login = ft.TextField(label='Login', hint_text='12345678', dense=True, expand=True,
                                  keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter())
        self.server = ft.TextField(label='Server', hint_text='VantageInternational-Live 3', dense=True, expand=True)
        self.password = ft.TextField(label='Investor password', password=True, can_reveal_password=True, dense=True,
                                     expand=True)
        self.enabled = ft.Checkbox(label='Include in the dashboard', value=True)
        self.form_title = ft.Text('Add account', size=12, weight=ft.FontWeight.W_600)
        self.cancel = ft.TextButton('Cancel', visible=False, on_click=lambda e: self.reset())
        self.save = ft.FilledButton('Add account', on_click=self.on_save)
        self.msg = ft.Text('', size=12)
        warn = app.C['neg']
        section = lambda t: ft.Text(t.upper(), size=12, weight=ft.FontWeight.W_600, color=app.C['muted'])
        content = ft.Column([
            section('MT5 terminal'),
            ft.Row([self.term, ft.OutlinedButton('Save', on_click=self.on_terminal)]),
            ft.Text("Use a terminal for monitoring only: logging in switches that terminal's account, so never use "
                    "the terminal that runs your EAs.", size=12, color=warn),
            ft.Divider(),
            section('Auto refresh'),
            ft.Row([self.auto, ft.OutlinedButton('Save', on_click=self.on_auto)]),
            ft.Text('Fetches every account every N minutes while the app is open (at least %d). The terminal is '
                    'started minimized for each fetch and closed afterwards.' % MIN_AUTO_REFRESH, size=12,
                    color=app.C['muted']),
            ft.Divider(),
            section('Accounts'),
            self.rows,
            ft.Divider(),
            self.form_title,
            ft.Row([self.name, self.login]),
            ft.Row([self.server, self.password]),
            ft.Row([self.enabled, ft.Container(expand=True), self.cancel, self.save]),
            ft.Text('Investor (read-only) password only. It is stored encrypted for your Windows user and never shown '
                    'again; leave it empty when editing to keep it.', size=12, color=app.C['muted']),
            self.msg,
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, width=720)
        self.dlg = ft.AlertDialog(
            title=ft.Row([ft.Text('Settings'), ft.IconButton(ft.Icons.CLOSE, tooltip='Close', on_click=self.close)],
                         alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=content, on_dismiss=self.on_dismiss)
        self.show_accounts()

    def open(self):
        self.page.show_dialog(self.dlg)

    def close(self, e=None):
        self.page.pop_dialog()

    def on_dismiss(self, e):
        if self.changed:
            self.app.on_refresh()

    def say(self, text, bad=False):
        self.msg.value = text
        self.msg.color = self.app.C['neg'] if bad else None
        self.page.update()

    def show_accounts(self):
        C, rows = self.app.C, []
        for a in self.store.accounts():
            rows.append(ft.Container(ft.Row([
                ft.Text(a['name'], expand=3), ft.Text(str(a['login']), expand=2), ft.Text(a['server'], expand=4),
                ft.TextButton('Edit', on_click=lambda e, a=a: self.edit(a)),
                ft.TextButton('Delete', on_click=lambda e, a=a: self.ask_delete(a)),
            ]), opacity=1 if a['enabled'] else 0.5, border=ft.Border.only(bottom=ft.BorderSide(1, C['line'])),
                padding=ft.Padding.symmetric(vertical=2, horizontal=4)))
        self.rows.controls = rows or [ft.Text('No accounts yet.', color=C['muted'])]

    def reset(self):
        self.editing = None
        for f in (self.name, self.login, self.server, self.password):
            f.value = ''
        self.enabled.value = True
        self.form_title.value = self.save.content = 'Add account'
        self.cancel.visible = False
        self.page.update()

    def edit(self, a):
        self.editing = a['id']
        self.name.value, self.login.value, self.server.value = a['name'], str(a['login']), a['server']
        self.password.value, self.enabled.value = '', a['enabled']
        self.form_title.value = 'Edit %s' % a['name']
        self.save.content = 'Save'
        self.cancel.visible = True
        self.page.update()

    def on_terminal(self, e):
        path = (self.term.value or '').strip()
        if path and not path.lower().endswith('terminal64.exe'):
            return self.say('the path must end with terminal64.exe', True)
        self.store.set('terminal_path', path)
        self.changed = True
        self.say('Terminal path saved.')

    def on_auto(self, e):
        n = int(self.auto.value or 0)
        if 0 < n < MIN_AUTO_REFRESH:
            return self.say('auto refresh: at least %d minutes, or 0 for off' % MIN_AUTO_REFRESH, True)
        self.store.set('refresh_minutes', str(n))
        self.app.render()
        self.say('Auto refresh every %d minutes.' % n if n else 'Auto refresh off.')

    def on_save(self, e):
        name = self.name.value
        try:
            self.store.save_account(name, self.login.value or 0, self.server.value, self.password.value,
                                    bool(self.enabled.value), self.editing)
        except Exception as err:
            msg = 'an account with this login and server already exists' if 'UNIQUE' in str(err) else str(err)
            return self.say(msg, True)
        self.changed = True
        self.show_accounts()
        self.reset()
        self.say('%s saved.' % name)

    def ask_delete(self, a):
        def yes(e):
            self.page.pop_dialog()
            self.store.delete_account(a['id'])
            self.changed = True
            if self.editing == a['id']:
                self.reset()
            self.show_accounts()
            self.say('%s deleted.' % a['name'])

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text('Delete account'), content=ft.Text('Delete %s (%s)?' % (a['name'], a['login'])),
            actions=[ft.TextButton('Cancel', on_click=lambda e: self.page.pop_dialog()),
                     ft.FilledButton('Delete', on_click=yes)]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--demo', action='store_true', help='random demo data, no MT5 needed')
    ap.add_argument('--db', default=str(DB), help='SQLite database (default data/metadashboard.db)')
    ap.add_argument('--web', action='store_true', help='open in the browser instead of a window')
    a = ap.parse_args()
    store = open_store(Path(a.db))

    async def _main(page: ft.Page):
        page.window.width, page.window.height = 1400, 1000
        App(page, store, a.demo)

    ft.run(_main, view=ft.AppView.WEB_BROWSER if a.web else ft.AppView.FLET_APP)


if __name__ == '__main__':
    main()
