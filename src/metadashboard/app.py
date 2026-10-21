"""MetaDashboard desktop app (Flet): profit calendar for several MT5 accounts, with settings and refresh.

    uv run metadashboard           # the app: shows the data last fetched, Refresh fetches every account
    uv run metadashboard --demo    # random demo data, no MT5 needed
    uv run metadashboard --web     # open it in the browser instead of a window
    metadashboard --install-shortcuts   # Start menu + desktop shortcuts (--remove-shortcuts before uninstalling)

Same numbers as the HTML page written by core.py: daily % = trading P/L / balance at the day's first trade,
month / year / week % = P/L / balance at the start of the period's first trading day.
"""
import argparse
import asyncio
import calendar
import datetime as dt
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

import flet as ft

from . import monitor, shortcuts
from .core import CACHE, DB, ROOT, cache_file, demo_accounts, fetch_all, load_cached, open_store
from .terminal import running, show

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
# one colour per account in the Chart tab, in account order (never by rank): the dataviz reference categorical
# palette, validated for colour-blind readers on LIGHT / DARK panel (light: relief = the table under the charts)
SERIES_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
SERIES_DARK = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']
CHART_H = 240
AXIS_W = 52
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


def first_start(days, frm, to):
    """An account's balance at its first trading day in the period (0: no trades in it)."""
    return next((days[d]['start'] for d in sorted(days) if frm <= d <= to and days[d]['start'] > 0), 0)


def day_pct(v):
    return v['pl'] / v['start'] * 100 if v and v['start'] > 0 else None


def last_deposit(acc):
    """Date of the account's last deposit in its fetched history, or None."""
    try:
        days = json.loads(cache_file(acc).read_text(encoding='utf-8'))['days']
    except (OSError, ValueError, KeyError):
        return None
    deposits = [d for d, v in days.items() if v['deposit'] > 0]
    return max(deposits) if deposits else None


def nice_step(span, ticks=4):
    """Grid step for an axis covering span: 1, 2, 2.5 or 5 x a power of ten, about `ticks` steps."""
    raw = span / ticks
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)


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
        self.acc, self.y, self.m, self.d = 'all', today.year, today.month - 1, today.day
        self.tab, self.mode = 'calendar', 'month'  # tab: calendar / chart; mode: day / month / year (both tabs)
        self.suggestions, self.focused, self.blurred = {}, None, (None, 0.0)
        self.dark = page.platform_brightness == ft.Brightness.DARK
        self.narrow = False
        self.busy = False
        self.session = False  # the monitoring terminal is open for the user to log in: no fetch meanwhile
        page.title = 'Meta Dashboard'
        page.padding = 0
        page.spacing = 0
        page.theme = ft.Theme(color_scheme_seed=LIGHT['accent'])
        page.dark_theme = ft.Theme(color_scheme_seed=DARK['accent'])
        page.on_resize = self.on_resize
        page.on_keyboard_event = self.on_key
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
            if n and not self.busy and not self.session and time.monotonic() - self.last_refresh >= n * 60:
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
        if not self.accounts:
            parts = [self.empty()]
        elif self.tab == 'chart':
            parts = [self.compare(), self.note()]
        else:
            parts = [self.cards(), self.calendar(), self.note()]
        body = ft.Column(parts,
                         spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)
        self.page.controls.clear()
        self.page.controls.extend([self.header()] + ([self.toolbar()] if self.accounts else [])
                                  + [ft.Container(body, padding=ft.Padding.only(left=16, right=16, bottom=16),
                                                  expand=True)])
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
        C, items = self.C, [self.text('Meta Dashboard', 18, weight=ft.FontWeight.BOLD)]
        if self.accounts:
            names = {'all': 'All accounts'}
            for i, a in enumerate(self.accounts):
                names[str(i)] = '%s%s (%s)' % (a['name'], ' · %s' % a['login'] if a['login'] else '', a['currency'])
            items += [
                ft.SegmentedButton(segments=[ft.Segment('calendar', label=ft.Text('Calendar'),
                                                        icon=ft.Icons.CALENDAR_VIEW_MONTH),
                                             ft.Segment('chart', label=ft.Text('Chart'), icon=ft.Icons.BAR_CHART)],
                                   selected=[self.tab], show_selected_icon=False, on_change=self.on_tab),
                # the chart compares all accounts; the calendar shows one or all of them
                ft.Dropdown(value=self.acc, options=[ft.DropdownOption(key=k, text=names[k]) for k in self.keys()],
                            on_select=self.on_account, dense=True, width=300, visible=self.tab == 'calendar'),
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

    def toolbar(self):
        """The period, for both tabs: Day / Month / Year, the date (click it for a calendar) and Today."""
        C = self.C
        return ft.Container(ft.Row([
            ft.SegmentedButton(segments=[ft.Segment('day', label=ft.Text('Day')),
                                         ft.Segment('month', label=ft.Text('Month')),
                                         ft.Segment('year', label=ft.Text('Year'))],
                               selected=[self.mode], show_selected_icon=False, on_change=self.on_mode),
            ft.Row([ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip='Previous', on_click=lambda e: self.step(-1)),
                    ft.TextButton(self.period_label(), icon=ft.Icons.CALENDAR_MONTH, on_click=self.pick_date,
                                  tooltip='Pick a date', style=ft.ButtonStyle(color=C['text'])),
                    ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip='Next', on_click=lambda e: self.step(1))],
                   spacing=0, tight=True),
            ft.OutlinedButton('Today', on_click=self.on_today),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(vertical=12, horizontal=16))

    def empty(self):
        return self.box(self.text('No account data yet. Open Settings to add the MT5 terminal and your accounts, '
                                  'then press Refresh.', color=self.C['muted'], text_align=ft.TextAlign.CENTER),
                        padding=32, alignment=ft.Alignment.CENTER)

    def bounds(self, mode=None):
        mode = mode or self.mode
        if mode == 'day':
            return (self.date().isoformat(),) * 2
        if mode == 'year':
            return iso(self.y, 0, 1), iso(self.y, 11, 31)
        return iso(self.y, self.m, 1), iso(self.y, self.m, 31)

    def cards(self):
        C, D, cur = self.C, combined_days(self.accounts, self.acc), currency(self.accounts, self.acc)
        P = self.span(*self.bounds())
        accs = self.accounts if self.acc == 'all' else [self.accounts[int(self.acc)]]
        rate = lambda a: RATE.get(a['currency'], 1) if self.acc == 'all' else 1
        bal = sum(a['balance'] * rate(a) for a in accs)
        eq = sum(a['equity'] * rate(a) for a in accs)
        money = lambda v: '{:,.2f}'.format(v) + (' ' + cur if cur != 'mixed' else '')
        label = self.mode.title()
        sign = self.sign_color(P['pl'])
        cards = [('Balance', money(bal), None), ('Equity', money(eq), None),
                 (label + ' P/L', fmt_amt(P['pl'], cur), sign), (label + ' %', fmt_pct(P['pct']) or '-', sign),
                 ('Winning / losing days', '%d / %d' % (P['up'], P['down']), None),
                 ('Closed trades', str(P['trades']), None)]
        return ft.ResponsiveRow([
            self.box(ft.Column([self.text(k, 12, C['muted']), self.text(v, 16 if self.narrow else 20, c, ft.FontWeight.W_600)],
                               spacing=2), col={'xs': 6, 'md': 4, 'lg': 2})
            for k, v, c in cards], spacing=12, run_spacing=12)

    def span(self, frm, to):
        """P/L and % of the selected account(s) over a period. All accounts: the % is on the sum of every account's
        own balance at its first trading day in the period, not only of the accounts that traded on its first day."""
        P = period(combined_days(self.accounts, self.acc), frm, to)
        if self.acc == 'all':
            start = sum(first_start(a['days'], frm, to) * RATE.get(a['currency'], 1) for a in self.accounts)
            P['pct'] = P['pl'] / start * 100 if start else None
        return P

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
        frm, to = self.bounds('year' if self.mode == 'year' else 'month')  # Day: its month, the day highlighted
        cap = max([1] + [abs(day_pct(v) or 0) for d, v in D.items() if frm <= d <= to])
        cur = currency(self.accounts, self.acc)
        return self.year_view(D, cap, cur) if self.mode == 'year' else self.month_view(D, cap, cur)

    def year_view(self, D, cap, cur):
        C, today, months = self.C, dt.date.today().isoformat(), []
        for m in range(12):
            M = self.span(iso(self.y, m, 1), iso(self.y, m, 31))
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
        chosen = self.date().isoformat() if self.mode == 'day' else None
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
            cells, week = [], []  # the week's days in this month
            for i in range(7):
                day = start + dt.timedelta(days=w * 7 + i)
                k, in_month = day.isoformat(), day.month == self.m + 1
                v = D.get(k)
                p = day_pct(v)
                if in_month:
                    week.append(k)
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
                    border=(ft.Border.all(3, C['text']) if k == chosen else ft.Border.all(2, C['accent'])
                            if k == today else ft.Border.all(1, C['line'])),
                    tooltip=tip, on_click=(lambda e, day=day: self.pick_day(day)) if in_month else None))
            if week_col:
                lines = [self.text('W%d' % (w + 1), 12, C['muted']), ft.Container(expand=True)]
                W = self.span(week[0], week[-1]) if week else None
                if W and W['pct'] is not None:
                    lines += [self.text(fmt_pct(W['pct']), 18, self.sign_color(W['pl']), ft.FontWeight.W_600),
                              self.text(fmt_amt(W['pl'], cur), 12, C['muted'])]
                cells.append(ft.Container(ft.Column(lines, spacing=0), expand=9, height=height, border_radius=10,
                                          padding=ft.Padding.symmetric(vertical=6, horizontal=8),
                                          border=ft.Border.all(1, C['line'])))
            rows.append(ft.Row(cells, spacing=3 if self.narrow else 6))
            w += 1
            if start + dt.timedelta(days=w * 7) > last:
                break
        return ft.Column(rows, spacing=3 if self.narrow else 6)

    # ------------------------------------------------------------------ compare
    def series_color(self, i):
        pal = SERIES_DARK if self.dark else SERIES_LIGHT
        return pal[i] if i < len(pal) else self.C['muted']  # past 8 accounts: no new hues, the labels tell them apart

    def date(self):
        """The selected day (its day of month clamped to the selected month)."""
        return dt.date(self.y, self.m + 1, min(self.d, calendar.monthrange(self.y, self.m + 1)[1]))

    def trading_days(self):
        return sorted({d for a in self.accounts for d, v in a['days'].items() if v['trades'] or v['pl']})

    def compare(self):
        """The selected day, month or year of every account side by side: one bar each, plus a table."""
        frm, to = self.bounds()
        if self.mode == 'day':
            title = 'Daily profit %% · %s' % self.date().strftime('%A %d %B %Y')
        elif self.mode == 'month':
            title = 'Monthly profit %% · %s %d' % (MONTHS[self.m], self.y)
        else:
            title = 'Yearly profit %% · %d' % self.y
        groups = []
        for i, a in enumerate(self.accounts):
            P = period(a['days'], frm, to)
            traded = P['up'] or P['down'] or P['trades']
            p = P['pct'] if traded else None
            tip = '%s: %s (%s)' % (a['name'], fmt_pct(p), fmt_amt(P['pl'], a['currency'])) if traded else None
            groups.append((a['name'], [(p, tip, self.series_color(i))]))
        return ft.Column([self.bar_chart(title, groups, values=True), self.compare_table(frm, to)], spacing=16)

    def on_mode(self, e):
        self.mode = e.control.selected[0] if e.control.selected else self.mode
        if self.mode == 'day':  # a day without trades shows nothing: start at the last trading day up to it
            days = [d for d in self.trading_days() if d <= self.date().isoformat()]
            if days and days[-1] != self.date().isoformat():
                self.y, self.m, self.d = int(days[-1][:4]), int(days[-1][5:7]) - 1, int(days[-1][8:])
        self.render()

    def bar_chart(self, title, groups, values=False):
        """groups: [(label, [(pct or None, tooltip, colour)])]: bars from the zero line, side by side per group.
        values: the % written at the end of each bar (for a few bars)."""
        C = self.C
        head = self.text(title, weight=ft.FontWeight.W_600)
        vals = [p for _, bars in groups for p, _, _ in bars if p is not None]
        if not vals:
            return self.box(ft.Column([head, self.text('No trades in this period.', 12, C['muted'])]))
        hi, lo = max(0.0, max(vals)), max(0.0, -min(vals))
        step = nice_step(max(hi + lo, 0.01))
        top, bottom = math.ceil(hi / step - 1e-9) * step, math.ceil(lo / step - 1e-9) * step
        top = top or (0 if bottom else step)
        pad = 22 if values else 0  # room for the value above / below a bar
        scale = (CHART_H - 2 * pad) / (top + bottom)
        zero = pad + top * scale
        ticks = [k * step for k in range(-round(bottom / step), round(top / step) + 1)]
        grid = [ft.Container(left=0, right=0, top=min(CHART_H - 1, zero - t * scale), height=1,
                             bgcolor=C['muted'] if abs(t) < 1e-9 else C['line']) for t in ticks]
        axis = [ft.Text(('%+g%%' % round(t, 4)) if abs(t) > 1e-9 else '0%', size=11, color=C['muted'],
                        left=0, width=AXIS_W - 8, text_align=ft.TextAlign.RIGHT,
                        top=min(CHART_H - 14, max(0, zero - t * scale - 8))) for t in ticks]
        cols = []
        for label, bars in groups:
            row = []
            for p, tip, color in bars:
                if p is None:
                    row.append(ft.Container(expand=1))
                    continue
                h = max(1.0, abs(p) * scale)
                up = p >= 0
                radius = (ft.BorderRadius.only(top_left=4, top_right=4) if up
                          else ft.BorderRadius.only(bottom_left=4, bottom_right=4))
                bar = ft.Container(height=h, bgcolor=color, border_radius=radius)
                parts = [ft.Container(height=zero - h if up else zero), bar]
                if values:
                    num = ft.Container(self.text(fmt_pct(p), 12, weight=ft.FontWeight.W_600), height=pad,
                                       alignment=ft.Alignment.BOTTOM_CENTER if up else ft.Alignment.TOP_CENTER)
                    parts = ([ft.Container(height=zero - h - pad), num, bar] if up
                             else [ft.Container(height=zero), bar, num])
                # the whole column is the hover target, bigger than a thin bar
                row.append(ft.Container(ft.Column(parts, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                        expand=1, height=CHART_H, tooltip=tip))
            inner = ft.Row(row, spacing=2)
            if values:  # few groups: keep the bars thin instead of filling the width
                inner = ft.Container(inner, width=72 * len(row))
            cols.append(ft.Container(inner, expand=1, alignment=ft.Alignment.TOP_CENTER,
                                     padding=ft.Padding.symmetric(horizontal=3)))
        plot = ft.Stack(grid + [ft.Row(cols, spacing=0, left=0, right=0, top=0, bottom=0)], height=CHART_H, expand=True)
        labels = ft.Row([ft.Container(self.text(label, 12, C['muted'], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                                text_align=ft.TextAlign.CENTER),
                                      expand=1, alignment=ft.Alignment.CENTER) for label, _ in groups],
                        spacing=0, expand=True)
        return self.box(ft.Column([
            head,
            ft.Row([ft.Stack(axis, width=AXIS_W, height=CHART_H), plot], spacing=0),
            ft.Row([ft.Container(width=AXIS_W), labels], spacing=0),
        ], spacing=10), padding=ft.Padding.only(left=8, right=16, top=12, bottom=12))

    def compare_table(self, frm, to):
        """The same numbers as a table: identity and values without relying on colour."""
        C, day = self.C, self.mode == 'day'
        cols = [('Account', 4), ('Profit %', 2), ('P/L', 3), ('Closed trades', 2)]
        cols += [('Start balance', 3)] if day else [('Win / loss days', 2), ('Best day', 2), ('Worst day', 2)]
        rows = [ft.Row([self.text(t, 12, C['muted'], expand=w) for t, w in cols])]
        for i, a in enumerate(self.accounts):
            P = period(a['days'], frm, to)
            traded = P['up'] or P['down'] or P['trades']
            cells = [((fmt_pct(P['pct']) if traded else '') or '-', P['pl']),
                     (fmt_amt(P['pl'], a['currency']) if traded else '-', P['pl']), (str(P['trades']), 0)]
            if day:
                v = a['days'].get(frm)
                cells.append(('{:,.2f} {}'.format(v['start'], a['currency']) if v else '-', 0))
            else:
                pcts = [p for p in (day_pct(v) for d, v in a['days'].items() if frm <= d <= to and v['pl'])
                        if p is not None]
                best, worst = (max(pcts), min(pcts)) if pcts else (None, None)
                cells += [('%d / %d' % (P['up'], P['down']), 0), (fmt_pct(best) or '-', best or 0),
                          (fmt_pct(worst) or '-', worst or 0)]
            rows.append(ft.Container(ft.Row(
                [ft.Row([ft.Container(width=12, height=12, border_radius=3, bgcolor=self.series_color(i)),
                         self.text(a['name'], 13, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True)],
                        spacing=8, expand=cols[0][1])]
                + [self.text(v, 13, self.sign_color(s), expand=w) for (v, s), (_, w) in zip(cells, cols[1:])]),
                border=ft.Border.only(top=ft.BorderSide(1, C['line'])), padding=ft.Padding.symmetric(vertical=8)))
        return self.box(ft.Column(rows, spacing=0))

    # ------------------------------------------------------------------ dates and suggestions
    def period_label(self):
        if self.mode == 'year':
            return str(self.y)
        if self.mode == 'day':
            return self.date().strftime('%d %b %Y')
        return '%s %d' % (MONTHS[self.m], self.y)

    def pick_date(self, e=None, value=None, on_pick=None):
        """Calendar picker; on_pick(date), by default the date shown by the views."""
        def chosen(ev):
            v = ev.control.value
            if v:
                (on_pick or self.set_date)(dt.date(v.year, v.month, v.day))

        today = dt.date.today()
        start = value or self.date()
        self.page.show_dialog(ft.DatePicker(value=dt.datetime(start.year, start.month, start.day),
                                            first_date=dt.datetime(2000, 1, 1),
                                            last_date=dt.datetime(today.year + 1, 12, 31), on_change=chosen))

    def set_date(self, d):
        self.y, self.m, self.d = d.year, d.month - 1, d.day
        self.render()

    def suggest(self, field, value):
        """Shell-like ghost text: an empty field shows `value` greyed out; Tab or the right arrow takes it."""
        field.hint_text = value or None
        if value:
            self.suggestions[id(field)] = (field, value)
        else:
            self.suggestions.pop(id(field), None)
        field.on_focus = lambda e: setattr(self, 'focused', field)
        field.on_blur = lambda e: self.left(field)

    def left(self, field):
        self.blurred = (field, time.monotonic())  # Tab moves the focus on before its key event arrives
        if self.focused is field:
            self.focused = None

    def on_key(self, e):
        if e.key not in ('Tab', 'Arrow Right') or e.shift or e.ctrl:
            return
        field = self.focused
        if field is None and self.blurred[0] is not None and time.monotonic() - self.blurred[1] < 0.5:
            field = self.blurred[0]
        hit = self.suggestions.get(id(field)) if field is not None else None
        if hit and not field.value:
            field.value = hit[1]
            self.page.update()

    def note(self):
        stale = [a['name'] for a in self.accounts if a.get('stale')]
        spans = [ft.TextSpan(
            'Loaded %s. Daily %% = trading P/L (profit + swap + commission) / balance when the day\'s first trade '
            'happens; deposits and withdrawals are not profit. Month / year %% = P/L / balance at the start of the '
            'period. Server dates.' % self.loaded
            + (' All accounts: cent accounts converted to their dollar.' if self.acc == 'all' and len(self.accounts) > 1 else '')
            + (' Auto refresh every %d min.' % self.minutes() if self.minutes() else '')
            + ''.join(' %s counts from %s.' % (a['name'], a['start_date']) for a in self.accounts
                      if a.get('start_date')))]
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

    def on_tab(self, e):
        self.tab = e.control.selected[0] if e.control.selected else self.tab
        self.render()

    def open_month(self, m):
        self.m, self.mode = m, 'month'
        self.render()

    def pick_day(self, day):
        self.mode = 'day'
        self.set_date(day)

    def step(self, d):
        if self.mode == 'day':  # to the previous / next day with trades
            here = self.date().isoformat()
            days = [x for x in self.trading_days() if (x > here if d > 0 else x < here)]
            nxt = dt.date.fromisoformat(days[0] if d > 0 else days[-1]) if days else self.date() + dt.timedelta(days=d)
            return self.set_date(nxt)
        if self.mode == 'year':
            self.y += d
        else:
            self.y, self.m = divmod(self.y * 12 + self.m + d, 12)
        self.render()

    def on_today(self, e):
        self.set_date(dt.date.today())

    def on_theme(self, e):
        self.dark = not self.dark
        self.render()

    def on_refresh(self, e=None, auto=False):
        if self.busy or self.session:
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
        self.term = ft.TextField(label='Or an existing monitoring terminal: terminal64.exe path',
                                 value=self.store.get('terminal_path'), dense=True, expand=True)
        self.term_box = ft.Column(spacing=8)
        self.auto = ft.TextField(label='Auto refresh, minutes (0 = off)', value=str(app.minutes()), dense=True,
                                 width=260, keyboard_type=ft.KeyboardType.NUMBER,
                                 input_filter=ft.NumbersOnlyInputFilter())
        self.rows = ft.Column(spacing=0)
        self.name = ft.TextField(label='Name', dense=True, expand=True)
        self.login = ft.TextField(label='Login', dense=True, expand=True,
                                  keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter())
        self.server = ft.TextField(label='Server', dense=True, expand=True)
        self.password = ft.TextField(label='Investor password (optional)', password=True, can_reveal_password=True,
                                     dense=True, expand=True)
        self.start = ft.TextField(label='Count from (optional)', dense=True, width=240,
                                  suffix_icon=ft.IconButton(ft.Icons.CALENDAR_MONTH, tooltip='Pick a date',
                                                            on_click=self.pick_start))
        self.enabled = ft.Checkbox(label='Include in the dashboard', value=True)
        self.form_title = ft.Text('Add account', size=12, weight=ft.FontWeight.W_600)
        self.cancel = ft.TextButton('Cancel', visible=False, on_click=lambda e: self.reset())
        self.save = ft.FilledButton('Add account', on_click=self.on_save)
        self.msg = ft.Text('', size=12)
        warn = app.C['neg']
        section = lambda t: ft.Text(t.upper(), size=12, weight=ft.FontWeight.W_600, color=app.C['muted'])
        content = ft.Column([
            section('MT5 terminal'),
            self.term_box,
            ft.Row([self.term, ft.OutlinedButton('Save', on_click=self.on_terminal)]),
            ft.Text("Logging in switches the account of this terminal, so it must be a copy used only by MetaDashboard, "
                    "never the terminal that runs your EAs.", size=12, color=warn),
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
            ft.Text('Only needed for an account the terminal has not saved: accounts logged in to the monitoring '
                    'terminal are added by themselves.', size=12, color=app.C['muted']),
            ft.Row([self.name, self.login]),
            ft.Row([self.server, self.password]),
            ft.Row([self.start, self.enabled, ft.Container(expand=True), self.cancel, self.save]),
            ft.Text('Count from: only the history from that date counts (Calendar, Chart, totals), e.g. for an old '
                    'account that traded another strategy before. Empty = the whole history. Grey text in an empty '
                    'field is a suggestion: press Tab or → to use it.', size=12, color=app.C['muted']),
            ft.Text('Investor (read-only) password only, and only when it is not saved in the monitoring terminal. It '
                    'is stored encrypted for your Windows user and never shown again; leave it empty when editing to '
                    'keep it.', size=12, color=app.C['muted']),
            self.msg,
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO, width=720)
        self.dlg = ft.AlertDialog(
            title=ft.Row([ft.Text('Settings'), ft.IconButton(ft.Icons.CLOSE, tooltip='Close', on_click=self.close)],
                         alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=content, on_dismiss=self.on_dismiss)
        self.show_terminal()
        self.show_accounts()
        self.suggest_form()
        mon = [p for p in (Path(r'C:\MT5-Monitor\terminal64.exe'), ROOT / 'mt5' / 'terminal64.exe') if p.is_file()]
        app.suggest(self.term, str(mon[-1]) if mon and not self.term.value else None)

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

    def show_terminal(self):
        """Create the monitoring terminal, or open it to log in to the accounts."""
        C, path = self.app.C, self.store.get('terminal_path')
        muted = dict(size=12, color=C['muted'])
        if path and Path(path).is_file():
            self.term_box.controls = [
                ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=C['pos'], size=18),
                        ft.Text(path, expand=True, selectable=True)]),
                ft.Row([ft.FilledButton('Log in to accounts', icon=ft.Icons.LOGIN, on_click=self.on_session,
                                        disabled=self.app.session),
                        ft.OutlinedButton('Find accounts', icon=ft.Icons.SEARCH, on_click=lambda e: self.find())]),
                ft.Text('Log in to accounts opens the monitoring terminal. Log in once to each account (File > Login '
                        'to Trade Account) with its investor password and "Save password" ticked, then close the '
                        'terminal: the accounts are added below and fetched.', **muted),
            ]
            return
        sources = monitor.installed_terminals()
        if not sources:
            self.term_box.controls = [ft.Text('No MetaTrader 5 found in Program Files. Install MetaTrader 5 (from '
                                              'your broker or metatrader5.com), then open Settings again.',
                                              size=12, color=C['neg'])]
            return
        self.source = ft.Dropdown(label='Copy from', value=str(sources[0]), dense=True, expand=True,
                                  options=[ft.DropdownOption(key=str(p), text=str(p.parent)) for p in sources])
        self.create_btn = ft.FilledButton('Create monitoring terminal', icon=ft.Icons.ADD, on_click=self.on_create)
        self.term_box.controls = [
            ft.Text('MetaDashboard makes its own copy of MetaTrader 5 to log in with, with the broker servers your '
                    'MetaTrader knows (not its logins). Your MetaTrader is not started or changed.', **muted),
            ft.Row([self.source, self.create_btn]),
        ]

    def on_create(self, e):
        self.create_btn.disabled = True
        self.say('Copying MetaTrader 5, this takes a moment…')
        self.page.run_thread(self.create, Path(self.source.value))

    def create(self, source):
        try:
            exe = monitor.create(source, ROOT / 'mt5', log=print)
        except Exception as err:
            self.create_btn.disabled = False
            return self.say('Could not copy MetaTrader 5: %s' % err, True)
        self.store.set('terminal_path', str(exe))
        self.term.value = str(exe)
        self.show_terminal()
        self.say('Monitoring terminal ready. Next: Log in to accounts.')

    def on_session(self, e):
        if self.app.busy:
            return self.say('Wait until the refresh has finished.', True)
        path = self.store.get('terminal_path')
        self.app.session = True
        self.show_terminal()
        self.say('The monitoring terminal is open: log in to each account with "Save password" ticked, then close it.')
        if not running(path):
            subprocess.Popen([path, '/portable'], cwd=str(Path(path).parent))
        self.page.run_thread(self.session_done, path)

    def session_done(self, path):
        show(path)  # restored and in front: it reopens minimized after a fetch
        time.sleep(2)
        while running(path):  # until the user closes the terminal
            time.sleep(2)
        self.app.session = False
        self.show_terminal()
        if self.find():
            self.app.on_refresh()

    def find(self):
        """Add the accounts that have logged in to the monitoring terminal; returns how many were new."""
        path = self.store.get('terminal_path')
        known = {(a['login'], a['server']) for a in self.store.accounts()}
        new = [a for a in monitor.accounts(path) if a not in known] if path else []
        for login, server in new:
            self.store.save_account(monitor.broker(server), login, server)
        self.show_accounts()
        if new:
            self.changed = True
            self.say('Added: %s.' % ', '.join('%s %d' % (monitor.broker(s), l) for l, s in new))
        else:
            self.say('No new accounts in the monitoring terminal. Log in to accounts first.')
        return len(new)

    def show_accounts(self):
        C, rows = self.app.C, []
        for a in self.store.accounts():
            rows.append(ft.Container(ft.Row([
                ft.Text(a['name'], expand=3), ft.Text(str(a['login']), expand=2), ft.Text(a['server'], expand=4),
                ft.Text('from ' + a['start_date'] if a['start_date'] else '', size=12, color=C['muted'], expand=2),
                ft.TextButton('Edit', on_click=lambda e, a=a: self.edit(a)),
                ft.TextButton('Delete', on_click=lambda e, a=a: self.ask_delete(a)),
            ]), opacity=1 if a['enabled'] else 0.5, border=ft.Border.only(bottom=ft.BorderSide(1, C['line'])),
                padding=ft.Padding.symmetric(vertical=2, horizontal=4)))
        self.rows.controls = rows or [ft.Text('No accounts yet.', color=C['muted'])]

    def reset(self):
        self.editing = None
        for f in (self.name, self.login, self.server, self.password, self.start):
            f.value = ''
        self.enabled.value = True
        self.form_title.value = self.save.content = 'Add account'
        self.cancel.visible = False
        self.suggest_form()
        self.page.update()

    def suggest_form(self, editing=None):
        """Suggestions: a new form offers the next account logged in to the monitoring terminal but not added yet;
        Count from offers the account's last deposit (a new strategy usually starts with one)."""
        app, path = self.app, self.store.get('terminal_path')
        if editing:
            for f in (self.name, self.login, self.server):
                app.suggest(f, None)
            app.suggest(self.start, last_deposit(editing))
            return
        known = {(a['login'], a['server']) for a in self.store.accounts()}
        new = [a for a in monitor.accounts(path) if a not in known] if path and Path(path).is_file() else []
        login, server = new[0] if new else (None, None)
        app.suggest(self.name, monitor.broker(server) if server else None)
        app.suggest(self.login, str(login) if login else None)
        app.suggest(self.server, server)
        app.suggest(self.start, None)

    def pick_start(self, e):
        def chosen(d):
            self.start.value = d.isoformat()
            self.page.update()
        try:
            value = dt.date.fromisoformat(self.start.value or self.start.hint_text or '')
        except ValueError:
            value = dt.date.today()
        self.app.pick_date(value=value, on_pick=chosen)

    def edit(self, a):
        self.editing = a['id']
        self.name.value, self.login.value, self.server.value = a['name'], str(a['login']), a['server']
        self.password.value, self.enabled.value, self.start.value = '', a['enabled'], a['start_date']
        self.form_title.value = 'Edit %s' % a['name']
        self.save.content = 'Save'
        self.cancel.visible = True
        self.suggest_form(editing=a)
        self.page.update()

    def on_terminal(self, e):
        path = (self.term.value or '').strip()
        if path and not path.lower().endswith('terminal64.exe'):
            return self.say('the path must end with terminal64.exe', True)
        self.store.set('terminal_path', path)
        self.changed = True
        self.show_terminal()
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
                                    bool(self.enabled.value), self.editing, self.start.value)
        except Exception as err:
            msg = 'an account with this login and server already exists' if 'UNIQUE' in str(err) else str(err)
            return self.say(msg, True)
        self.changed = True
        self.show_accounts()
        self.reset()
        self.app.load()  # a new start date shows at once, without waiting for a fetch
        self.app.render()
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
    ap.add_argument('--install-shortcuts', action='store_true', help='add Start menu and desktop shortcuts, then exit')
    ap.add_argument('--remove-shortcuts', action='store_true', help='remove those shortcuts, then exit')
    a = ap.parse_args()
    if a.install_shortcuts:
        return shortcuts.install(ROOT)
    if a.remove_shortcuts:
        return shortcuts.remove()
    store = open_store(Path(a.db))

    async def _main(page: ft.Page):
        page.window.width, page.window.height = 1400, 1000
        page.window.icon = str(shortcuts.ICON)
        App(page, store, a.demo)

    ft.run(_main, view=ft.AppView.WEB_BROWSER if a.web else ft.AppView.FLET_APP)


def gui():
    """Start menu / desktop shortcut (no console window): output goes to data/metadashboard.log."""
    if sys.stdout is None or sys.stderr is None:
        CACHE.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(CACHE / 'metadashboard.log', 'a', encoding='utf-8', buffering=1)
    main()


if __name__ == '__main__':
    main()
