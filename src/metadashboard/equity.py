"""Equity drawdown rebuilt from the deal history and the symbols' M1 bars, the way MT5's own report does it.

Every minute a position is open, the floating P/L of a symbol's positions is taken at the worse of the minute's low
and high (one price for all of them, so a hedge is not counted as a loss) and added to the balance from the deals. Deposits and withdrawals do not count: the equity is kept as
an index that only trading moves. An approximation: per minute, a position's profit linear in the price (its value
per lot and point taken from its own closing deal, else from the terminal), and a position closed within a minute
still counted for that minute.

Per server day: [open, high, low, close, ddi] of that index; ddi = the day's deepest drop below its running high
(0..1). max_dd() turns those into the max drawdown of any period.
"""
import datetime as dt

MERGE_GAP = 6 * 3600  # fetch the M1 bars of positions this close together in one request


def _utc(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc)


def _day(ts):
    return (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=ts)).date().isoformat()  # server time, like the deals


def _lot_value(mt5, symbol, price):
    """Account currency per lot per 1.0 of price, from the terminal."""
    info = mt5.symbol_info(symbol)
    step = (info.point if info and info.point else 0.00001) * 1000
    value = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, 1.0, price, price + step)
    if value:
        return value / step
    return info.trade_tick_value / info.trade_tick_size if info and info.trade_tick_size else 0.0


def _positions(mt5, deals):
    """{position id: dict(symbol, sign, price, k, changes=[(time, volume after)])} from the buy / sell deals."""
    out = {}
    for d in deals:
        if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue
        p = out.setdefault(d.position_id, dict(symbol=d.symbol, sign=0, vol=0.0, price=0.0, k=None, changes=[]))
        side = 1 if d.type == mt5.DEAL_TYPE_BUY else -1
        if d.entry == mt5.DEAL_ENTRY_IN:
            new = p['vol'] + d.volume
            p['price'] = (p['price'] * p['vol'] + d.price * d.volume) / new if new else d.price
            p['vol'], p['sign'] = new, p['sign'] or side
        else:  # OUT, OUT_BY, INOUT
            if p['sign'] and d.volume and d.profit and abs(d.price - p['price']) > 1e-12 and p['k'] is None:
                p['k'] = d.profit / ((d.price - p['price']) * p['sign'] * d.volume)
            closed = min(p['vol'], d.volume)
            p['vol'] -= closed
            if d.entry == mt5.DEAL_ENTRY_INOUT and d.volume > closed:  # a reversal opens the other way
                p['vol'], p['sign'], p['price'] = d.volume - closed, side, d.price
        p['changes'].append((d.time, p['vol']))
    return out


def _bars(mt5, symbol, spans, log):
    """{minute: (high, low, close)} of the symbol over the spans (server-time seconds)."""
    spans = sorted(spans)
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a - merged[-1][1] <= MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    mt5.symbol_select(symbol, True)
    out = {}
    for a, b in merged:
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, _utc(a - 120), _utc(b + 120))
        for r in (rates if rates is not None else []):
            out[int(r['time'])] = (float(r['high']), float(r['low']), float(r['close']))
    if not out:
        log('  %s: no M1 history, its floating P/L is left out' % symbol)
    return out


def equity_days(mt5, deals, now, log=print):
    """deals: the account's history_deals_get() result; now: server time (seconds) for positions still open."""
    deals = sorted(deals, key=lambda d: (d.time_msc, d.ticket))
    if not deals:
        return {}
    positions = _positions(mt5, deals)
    spans = {}
    for p in positions.values():
        start, end = p['changes'][0][0], p['changes'][-1][0] if p['vol'] <= 0 else now
        p['span'] = (start, end)
        spans.setdefault(p['symbol'], []).append((start, end))
    bars = {s: _bars(mt5, s, sp, log) for s, sp in spans.items()}
    for p in positions.values():
        if p['k'] is None:  # never closed with a price move (or still open): ask the terminal
            p['k'] = _lot_value(mt5, p['symbol'], p['price'])
    minutes = sorted({t for b in bars.values() for t in b})  # minutes without open positions are skipped below

    by_pos = {pid: iter(p['changes']) for pid, p in positions.items()}
    nxt = {pid: next(it) for pid, it in by_pos.items()}
    open_vol = {}  # position id -> volume now
    last = {}  # symbol -> last close
    balance, scale, days = 0.0, None, {}
    state = dict(close=None)

    def floating(price_of):
        total = 0.0
        for pid, vol in open_vol.items():
            p = positions[pid]
            price = price_of(p)
            if price is not None:
                total += p['k'] * vol * p['sign'] * (price - p['price'])
        return total

    def note(ts, i_close, i_worst):
        day = _day(ts)
        r = days.get(day)
        if r is None:
            o = state['close'] if state['close'] is not None else i_close
            r = days[day] = [o, o, o, o, 0.0, o]  # open, high, low, close, ddi, running high
        r[4] = max(r[4], 1 - i_worst / r[5] if r[5] > 0 else 0.0)
        r[2] = min(r[2], i_worst, i_close)
        r[1], r[3], r[5] = max(r[1], i_close), i_close, max(r[5], i_close)
        state['close'] = i_close

    events = [(d.time, 0, d) for d in deals] + [(t, 1, None) for t in minutes]
    events.sort(key=lambda e: (e[0], e[1]))  # a bar before the deals inside its minute
    for ts, kind, d in events:
        if kind == 1:  # a minute: the open positions at that minute's prices
            if not open_vol or scale is None:
                continue
            for pid in open_vol:
                bar = bars[positions[pid]['symbol']].get(ts)
                if bar:
                    last[positions[pid]['symbol']] = bar[2]
            close = balance + floating(lambda p: last.get(p['symbol']))
            # a symbol has one price at a time: its positions together are worst at the minute's low or its high
            # (never a buy at the low and a sell at the high at once, which would count a hedge as a loss)
            low = balance
            for symbol in {positions[pid]['symbol'] for pid in open_vol}:
                bar = bars[symbol].get(ts)
                ends = (bar[1], bar[0]) if bar else (last.get(symbol),)
                low += min(floating(lambda p, x=x: x if p['symbol'] == symbol else None) for x in ends)
            if close > 0:
                note(ts, scale * close, scale * max(low, 0.0))
            continue
        amount = d.profit + d.swap + d.commission + getattr(d, 'fee', 0.0)
        if d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            balance += amount
            last[d.symbol] = d.price  # the market now; the last bar seen may be months old
            pid = d.position_id
            _, vol = nxt[pid]
            nxt[pid] = next(by_pos[pid], (None, vol))
            if vol > 0:
                open_vol[pid] = vol
            else:
                open_vol.pop(pid, None)
        else:  # deposit, withdrawal, credit, ...: moves the equity, not the index
            before = balance + floating(lambda p: last.get(p['symbol'], p['price']))
            balance += amount
            after = balance + floating(lambda p: last.get(p['symbol'], p['price']))
            if after > 0:
                index = scale * before if scale is not None and before > 0 else 0.0
                scale = (index if index > 0 else (state['close'] or 1.0)) / after
        if scale is not None:
            eq = balance + floating(lambda p: last.get(p['symbol'], p['price']))
            if eq > 0:
                note(ts, scale * eq, scale * eq)
    return {day: [round(x, 6) for x in r[:5]] for day, r in days.items()}


def max_dd(eq, frm, to):
    """Max equity drawdown of a period in % (from the period's start; deposits / withdrawals do not count), or None
    when there is no equity data in it."""
    peak, worst = None, 0.0
    for day in sorted(d for d in eq if frm <= d <= to):
        o, h, low, c, ddi = eq[day]
        if peak is None:
            peak = o
        worst = max(worst, ddi, 1 - low / peak if peak > 0 else 0.0)
        peak = max(peak, h)
    return None if peak is None else worst * 100
