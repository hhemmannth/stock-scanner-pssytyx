#!/usr/bin/env python3
"""
strategy_scanner.py - scans NSE stocks and the Nifty index with your rule book:
  structure (CHoCH -> BOS with displacement) -> FVG + order block -> pullback into the zone
  -> rejection + close back through the 9 EMA on strong volume -> structural stop.

Three sections, one engine:
  swing     Nifty 500 stocks, LONG ONLY.   1D structure  -> 1H trigger
  options   Nifty 50 index, calls + puts.  15m bias      -> 5m structure + 5m trigger
  intraday  most liquid Nifty 500 stocks, long + short.  15m bias -> 5m structure + 5m trigger

Usage:   python strategy_scanner.py --mode swing --out _site/data
         python strategy_scanner.py --mode live            (options + intraday)
Writes swing.json / options.json / intraday.json for the web page. Not investment advice.
"""
import argparse, io, json, math, os, sys, time, urllib.request
import numpy as np
import pandas as pd

# ------------------------------------------------------------------ settings
CFG = dict(                       # swing: structure on 1D, trigger on 1H
    pivot=3, atr_n=14, lookback=150, disp_body_atr=1.0, fvg_min_atr=0.2, stack_gap_atr=0.5, approach_atr=1.5,
    sl_buffer_atr=0.25, rvol_min=1.5, rvol_n=20, h_lookback=40, trigger_age=2,
    min_price=50.0, min_turnover_cr=20.0, min_bars=60,
    max_bos_age=60, max_zone_atr=3.5, max_zone_pct=10.0, trigger_max_atr=1.0)
CFG_I = dict(CFG, lookback=240, h_lookback=48, trigger_age=3, min_bars=120, min_price=0.0, min_turnover_cr=0.0,
             max_bos_age=90, max_zone_atr=3.0, max_zone_pct=3.0)         # options + intraday: structure and trigger on 5m
CFG_B = dict(CFG_I, lookback=160, max_bos_age=120, max_zone_atr=6.0, max_zone_pct=6.0, min_bars=60)   # 15m bias check
PAIRS = [('zone_bot', 'zone_top'), ('ob_low', 'ob_high'), ('fvg_low', 'fvg_high'), ('fib_lo', 'fib_hi'), ('leg_low', 'leg_high')]
SINGLES = ['entry', 'sl', 't1', 't2', 't3', 'price', 'bos_level', 'choch_level']
COLS = ['Open', 'High', 'Low', 'Close', 'Volume']
IST = 'Asia/Kolkata'

# ------------------------------------------------------------------ indicators
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def atr(df, n=14):
    tr = pd.concat([df.High - df.Low, (df.High - df.Close.shift()).abs(), (df.Low - df.Close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def invert(df, K):
    """Mirror prices (p -> K - p) so the long logic can find short setups. EMA and ATR commute with this."""
    o = df.copy(); o['Open'], o['High'], o['Low'], o['Close'] = K - df.Open, K - df.Low, K - df.High, K - df.Close
    return o

def swing_points(df, n):
    h, l = df.High.values, df.Low.values; ph, pl = [], []
    for i in range(n, len(df) - n):
        if h[i] >= h[i - n:i].max() and h[i] > h[i + 1:i + n + 1].max(): ph.append(i)
        if l[i] <= l[i - n:i].min() and l[i] < l[i + 1:i + n + 1].min(): pl.append(i)
    return ph, pl

# ------------------------------------------------------------------ structure
def find_structures(df, cfg):
    """Candidate (CHoCH, BOS, zone) structures, newest first."""
    N = len(df); o, h, l, c = (df[k].values for k in ('Open', 'High', 'Low', 'Close'))
    a = atr(df, cfg['atr_n']).values; n = cfg['pivot']; ph, pl = swing_points(df, n); out = []
    for ci in range(N - 1, max(n * 3, N - cfg['lookback']) - 1, -1):
        phs = [i for i in ph if i + n <= ci - 1]; pls = [i for i in pl if i + n <= ci - 1]
        if len(phs) < 2 or len(pls) < 2: continue
        lh, lh2 = phs[-1], phs[-2]
        if not h[lh] < h[lh2]: continue                      # last swing high is a lower high
        if not l[pls[-1]] < l[pls[-2]]: continue             # and lows are falling: a downtrend
        lvl = h[lh]
        if not c[ci] > lvl or np.any(c[lh + 1:ci] > lvl): continue       # first close above only = CHoCH
        base_low = l[pls[-1]]
        if np.any(l[ci:] < base_low): continue               # structure failed after the CHoCH
        bos, run, pulled = None, h[ci], False
        for j in range(ci + 1, N):
            if c[j] < o[j]: pulled = True
            aj = a[j - 1] if not math.isnan(a[j - 1]) else (h[j] - l[j])
            if pulled and c[j] > run and (c[j] - o[j]) >= cfg['disp_body_atr'] * aj: bos = j; break
            run = max(run, h[j])
        if bos is None: continue
        b = bos; a_b = a[b - 1] if not math.isnan(a[b - 1]) else (h[b] - l[b])
        ob = None
        for k in range(b - 1, max(ci, b - 6) - 1, -1):
            if c[k] < o[k]: ob = (l[k], o[k], k); break      # order block: last down candle before the displacement
        fvg = None
        for m in range(b - 1, min(b + 2, N - 1)):
            if m >= 1 and m + 1 < N and l[m + 1] > h[m - 1] and (l[m + 1] - h[m - 1]) >= cfg['fvg_min_atr'] * a_b:
                if fvg is None or (l[m + 1] - h[m - 1]) > (fvg[1] - fvg[0]): fvg = (h[m - 1], l[m + 1], m)
        if ob is None and fvg is None: continue
        zone_top = fvg[1] if fvg else ob[1]; zone_bot = ob[0] if ob else fvg[0]
        stacked = bool(ob and fvg and (fvg[0] - ob[1]) <= cfg['stack_gap_atr'] * a_b)
        leg_low = ob[0] if ob else l[b - 1]; leg_high = h[b:].max()
        if leg_high - leg_low < 2 * a_b: continue
        rng = leg_high - leg_low
        out.append(dict(choch_i=ci, bos_i=b, choch_level=lvl, bos_level=run, ob_low=ob[0] if ob else np.nan, ob_high=ob[1] if ob else np.nan,
                        fvg_low=fvg[0] if fvg else np.nan, fvg_high=fvg[1] if fvg else np.nan, zone_bot=zone_bot, zone_top=zone_top,
                        zone_q=2 if stacked else 1, leg_low=leg_low, leg_high=leg_high, fib_hi=leg_high - 0.618 * rng, fib_lo=leg_high - 0.705 * rng, atr=a[-1]))
        if len(out) >= 5: break
    return out

def zone_state(df, s, cfg, px_ref=None):
    c, l = df.Close.values, df.Low.values; a = s['atr']; b = s['bos_i']; px_ref = px_ref if px_ref is not None else c[-1]
    if len(c) - 1 - b > cfg['max_bos_age']: return 'STALE'
    height = s['zone_top'] - s['zone_bot']
    if height > cfg['max_zone_atr'] * a or 100 * height / px_ref > cfg['max_zone_pct']: return 'WIDE'
    if np.any(c[b + 1:] < s['zone_bot'] - cfg['sl_buffer_atr'] * a): return 'BROKEN'
    touch = l[max(b + 2, len(l) - 3):]                      # bars after the displacement candle; empty if the BOS is the last bar
    if c[-1] >= s['zone_bot'] and len(touch) and touch.min() <= s['zone_top']: return 'IN_ZONE'
    if c[-1] > s['zone_top'] and c[-1] - s['zone_top'] <= cfg['approach_atr'] * a: return 'APPROACH'
    return 'FAR'

def confirm(trig, s, cfg):
    """Trigger-frame confirmation: rejection in the zone, close back above the 9 EMA, relative volume."""
    res = dict(rejection=0, reclaim=0, rvol_ok=0, rvol=np.nan, trigger_ago=None, touched=False, pullback_low=np.nan)
    if trig is None or len(trig) < cfg['rvol_n'] + 5: return res
    e = ema(trig.Close, 9).values; o, h, l, c, v = (trig[k].values for k in ('Open', 'High', 'Low', 'Close', 'Volume'))
    N = len(trig); lo_i = max(0, N - cfg['h_lookback']); zb, zt, buf = s['zone_bot'], s['zone_top'], cfg['sl_buffer_atr'] * s['atr']
    touch = [i for i in range(lo_i, N) if l[i] <= zt and l[i] >= zb - 2 * buf]
    if not touch: return res
    res['touched'] = True; t0 = touch[0]; res['pullback_low'] = l[t0:].min()
    for i in touch:
        rg = h[i] - l[i]; body = abs(c[i] - o[i]) + 1e-9; lw = min(o[i], c[i]) - l[i]
        if rg > 0 and c[i] >= l[i] + 0.6 * rg and lw >= 0.5 * body: res['rejection'] = 1
    for t in range(N - 1, max(t0 + 1, N - 1 - cfg['trigger_age']) - 1, -1):
        if c[t] > e[t] and c[t - 1] <= e[t - 1]:
            res['reclaim'] = 1; res['trigger_ago'] = N - 1 - t
            base = v[max(0, t - cfg['rvol_n']):t]; rv = v[t] / base.mean() if len(base) and base.mean() > 0 else np.nan
            res['rvol'] = rv; res['rvol_ok'] = int(rv >= cfg['rvol_min']) if not math.isnan(rv) else 0
            break
    return res

def has_bias(df15):
    """15m bias for the intraday and options sections: a bullish CHoCH + BOS on the 15m that is still intact."""
    if df15 is None or len(df15) < CFG_B['min_bars']: return False
    for s in find_structures(df15, CFG_B):
        if zone_state(df15, s, CFG_B) not in ('BROKEN', 'STALE'): return True
    return False

# ------------------------------------------------------------------ scoring and plan
def grade(score): return 'A+' if score >= 8 else 'A' if score >= 6 else 'B' if score >= 4 else 'skip'

def round_in_zone(bot, top):
    step = 5 if top < 200 else 10 if top < 600 else 25 if top < 1500 else 50 if top < 4000 else 100 if top < 15000 else 500
    return math.floor(top / step) * step >= bot

def detect(struct, trig, cfg, K=None, mode='swing', bias=None, has_volume=True, levels=(), extra_ticks=(), section=None):
    struct = struct.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
    if len(struct) < cfg['min_bars']: return None
    px = struct.Close.iloc[-1]; px_o = px if K is None else K - px
    cands = find_structures(struct, cfg)
    if not cands: return None
    chosen = None
    for s in cands:
        st = zone_state(struct, s, cfg, px_o)
        if st in ('IN_ZONE', 'APPROACH'): chosen = (s, st); break
    if chosen is None: chosen = (cands[0], zone_state(struct, cands[0], cfg, px_o))
    s, state = chosen
    if state not in ('IN_ZONE', 'APPROACH'): return dict(symbol=None, state=state, score=0, grade='skip')
    bias_ok = None
    if mode == 'intraday':
        bias_ok = has_bias(bias)
        if not bias_ok: return dict(symbol=None, state='NO_BIAS', score=0, grade='skip')      # your rule: the 15m must agree
    cf = confirm(trig, s, cfg); a = s['atr']; ticks = []
    lv = [x if K is None else K - x for x in levels]
    zb_o, zt_o = (s['zone_bot'], s['zone_top']) if K is None else (K - s['zone_top'], K - s['zone_bot'])
    if round_in_zone(zb_o, zt_o) or (s['zone_bot'] - .25 * a <= s['bos_level'] <= s['zone_top'] + .25 * a) or any(s['zone_bot'] - .25 * a <= x <= s['zone_top'] + .25 * a for x in lv): ticks.append('key level')
    if min(s['fib_hi'], s['zone_top']) >= max(s['fib_lo'], s['zone_bot']): ticks.append('fib')
    if mode == 'swing':
        h_ok = trig is None or len(trig) < 15 or trig.Close.iloc[-1] > ema(trig.Close, 9).iloc[-1]
        if px >= ema(struct.Close, 21).iloc[-1] - .5 * a and h_ok: ticks.append('MTF EMA')      # daily trend intact, 1H aligned
    else:
        t_ok = trig.Close.iloc[-1] > ema(trig.Close, 9).iloc[-1]; b_ok = bias is None or bias.Close.iloc[-1] > ema(bias.Close, 9).iloc[-1]
        if t_ok and b_ok: ticks.append('MTF EMA')                                              # 5m and 15m on the same side
    ticks += [t for t in extra_ticks if t not in ticks]
    structure = 2 if mode == 'swing' else 1 + (1 if bias_ok else 0)
    conf = cf['rejection'] + cf['reclaim'] + (cf['rvol_ok'] if has_volume else 0); ctx = min(3, len(ticks)); score = structure + s['zone_q'] + conf + ctx
    triggered = bool(cf['reclaim'] and cf['touched']); last_t = trig.Close.iloc[-1] if trig is not None and len(trig) else px
    if triggered and (last_t - s['zone_top']) > cfg['trigger_max_atr'] * a: return dict(symbol=None, state='EXTENDED', score=0, grade='skip')
    if triggered and not has_volume: status = 'TRIGGER (check volume)'
    elif triggered and not cf['rvol_ok']: status = 'WATCH (trigger, low volume)'
    elif triggered: status = 'TRIGGERED'
    else: status = 'WATCH (in zone)' if state == 'IN_ZONE' else 'APPROACHING (set alert)'
    entry = last_t if status.startswith('TRIGGER') else s['zone_top'] - .25 * (s['zone_top'] - s['zone_bot'])
    base = s['ob_low'] if not math.isnan(s['ob_low']) else s['zone_bot']
    sl = min(base, cf['pullback_low'] if not math.isnan(cf['pullback_low']) else base) - cfg['sl_buffer_atr'] * a; risk = entry - sl; plan = {}
    if risk > 0: plan = dict(entry=entry, sl=sl, t1=s['leg_high'], t2=entry + 2 * risk, t3=entry + 3 * risk, risk_pct=100 * risk / (entry if K is None else K - entry), r_t1=(s['leg_high'] - entry) / risk)
    section = section or mode
    notes = ['check futures OI' if section == 'options' else 'check results date and sector']
    if section == 'options': notes += ['volume is not available for the index, check NIFTY1!', 'expiry day: skip afternoon entries or size down']
    elif not has_volume: notes.append('check volume on a chart')
    if plan and plan['r_t1'] < 1.5: notes.append('limited room to the prior high')
    if plan and plan['risk_pct'] > 7 and mode == 'swing': notes.append('wide stop: reduce size or skip')
    return dict(state=state, status=status, structure=structure, zone_q=s['zone_q'], confirm=conf, context=ctx, score=score, grade=grade(score),
                ticks=', '.join(ticks) or '-', rvol=cf['rvol'], price=px, choch_level=s['choch_level'], bos_level=s['bos_level'], zone_bot=s['zone_bot'], zone_top=s['zone_top'],
                ob_low=s['ob_low'], ob_high=s['ob_high'], fvg_low=s['fvg_low'], fvg_high=s['fvg_high'], fib_lo=s['fib_lo'], fib_hi=s['fib_hi'], leg_low=s['leg_low'], leg_high=s['leg_high'],
                choch_date=str(struct.index[s['choch_i']])[:16], bos_date=str(struct.index[s['bos_i']])[:16], notes='; '.join(notes), **plan)

def unflip(r, K):
    for lo, hi in PAIRS:
        if lo in r and hi in r: r[lo], r[hi] = K - r[hi], K - r[lo]
    for k in SINGLES:
        if k in r and r[k] is not None: r[k] = K - r[k]
    return r

def liquid(daily, cfg=CFG):
    return daily.Close.iloc[-1] >= cfg['min_price'] and (daily.Close * daily.Volume).tail(20).mean() / 1e7 >= cfg['min_turnover_cr']

def scan_symbol(daily, hourly=None, side='long', cfg=CFG, extra_ticks=()):
    """Swing scan. The rule book allows LONG only for swing trades, so any other side is refused."""
    if side != 'long': raise ValueError('swing trading is long only')
    daily = daily.dropna(subset=['Open', 'High', 'Low', 'Close'])
    if len(daily) < cfg['min_bars'] or not liquid(daily, cfg): return None
    return detect(daily, hourly, cfg, None, 'swing', extra_ticks=extra_ticks)

def scan_intraday(df5, df15, side='long', cfg=CFG_I, has_volume=True, levels=(), extra_ticks=(), section='intraday'):
    """Options (Nifty) and intraday (stocks): 15m bias, 5m structure and 5m trigger. Long = call/buy, short = put/sell."""
    df5 = df5.dropna(subset=['Open', 'High', 'Low', 'Close'])
    if len(df5) < cfg['min_bars']: return None
    if side == 'short':
        K = float(2 * df5.High.max())
        r = detect(invert(df5, K), invert(df5, K), cfg, K, 'intraday', bias=invert(df15, K) if df15 is not None else None, has_volume=has_volume, levels=levels, extra_ticks=extra_ticks, section=section)
        return unflip(r, K) if r and 'zone_bot' in r else r
    return detect(df5, df5, cfg, None, 'intraday', bias=df15, has_volume=has_volume, levels=levels, extra_ticks=extra_ticks, section=section)

def weekly_ok(daily):
    w = daily.Close.resample('W-FRI').last().dropna()
    if len(w) < 12: return False
    e = ema(w, 9); return bool(w.iloc[-1] >= e.iloc[-1] and e.iloc[-1] >= e.iloc[-3])

def index_ok(nifty_daily): return nifty_daily is not None and len(nifty_daily) > 30 and nifty_daily.Close.iloc[-1] >= ema(nifty_daily.Close, 21).iloc[-1]

def prev_day_levels(df5):
    d = df5.index.normalize(); days = sorted(set(d))
    if len(days) < 2: return []
    p = df5[d == days[-2]]; return [float(p.High.max()), float(p.Low.min())]

def has_volume(df): return len(df) > 0 and float((df.Volume > 0).mean()) > 0.5

# ------------------------------------------------------------------ universe
def parse_universe_csv(text):
    df = pd.read_csv(io.StringIO(text)); col = next((c for c in df.columns if c.strip().lower() == 'symbol'), None)
    if col is None: raise ValueError('no Symbol column')
    return [str(x).strip() for x in df[col].dropna() if str(x).strip()]

def load_nifty500(local='nifty500.csv', fallback='watchlist.txt', fetch=None):
    """Live Nifty 500 list from NSE Indices, else your uploaded nifty500.csv, else the short starter watchlist."""
    url = 'https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv'
    try:
        text = (fetch or _http_get)(url); syms = parse_universe_csv(text)
        if len(syms) >= 450: return syms, f'Nifty 500 (live list, {len(syms)} symbols)'
    except Exception as ex: print(f'  live Nifty 500 list unavailable: {ex}', file=sys.stderr)
    if os.path.exists(local):
        try:
            syms = parse_universe_csv(open(local, encoding='utf-8-sig').read())
            if len(syms) >= 450: return syms, f'Nifty 500 (your nifty500.csv, {len(syms)} symbols)'
        except Exception as ex: print(f'  {local} unreadable: {ex}', file=sys.stderr)
    syms = [x.strip() for x in open(fallback) if x.strip() and not x.startswith('#')]
    return syms, f'Fallback list of {len(syms)} symbols. Upload nifty500.csv to scan all 500.'

def _http_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36', 'Accept': 'text/csv,*/*'})
    return urllib.request.urlopen(req, timeout=30).read().decode('utf-8-sig')

# ------------------------------------------------------------------ data (yfinance)
def _yahoo(sym): return sym if sym.startswith('^') or sym.endswith('.NS') else sym + '.NS'

def _extract(d, t, multi):
    f = (d[t] if multi else d)[COLS].dropna()
    if f.empty: raise ValueError('no data returned')
    return f

def download_many(symbols, period, interval, chunk=50, pause=1.0):
    """Chunked yfinance download with one-by-one retries. Returns ({symbol: frame}, [failed symbols])."""
    import yfinance as yf
    out, missing = {}, []
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]; tick = [_yahoo(s) for s in part]
        kw = dict(group_by='ticker', auto_adjust=False, threads=True, progress=False)
        if len(tick) == 1: kw['multi_level_index'] = False
        try: d = yf.download(tick, period=period, interval=interval, **kw)
        except Exception as ex: print(f'  chunk failed: {ex}', file=sys.stderr); d = None
        for s, t in zip(part, tick):
            try: out[s] = _extract(d, t, len(tick) > 1)
            except Exception: missing.append((s, t))
        if i + chunk < len(symbols): time.sleep(pause)
    failed = []
    for s, t in missing:
        err = None
        for attempt in range(3):
            try:
                time.sleep(1.0 + attempt)
                out[s] = _extract(yf.download(t, period=period, interval=interval, auto_adjust=False, progress=False, threads=False, multi_level_index=False), t, False); err = None; break
            except Exception as ex: err = ex
        if err is not None: failed.append(s)
    return out, failed

def tidy_daily(df, now):
    if len(df) and df.index[-1].date() == now.date() and now.hour * 60 + now.minute < 15 * 60 + 45: df = df.iloc[:-1]
    df.index = pd.DatetimeIndex(df.index).tz_localize(None) if df.index.tz is not None else df.index
    return df

def tidy_intraday(df, now, minutes):
    if not len(df): return df
    df = df.copy(); df.index = df.index.tz_convert(IST) if df.index.tz is not None else df.index.tz_localize('UTC').tz_convert(IST)
    start = df.index[-1]; end = min(start + pd.Timedelta(minutes=minutes), start.normalize() + pd.Timedelta(hours=15, minutes=30))
    return df.iloc[:-1] if end > now else df

def market_open(now): return now.weekday() < 5 and (9 * 60 + 15) <= now.hour * 60 + now.minute <= (15 * 60 + 30)

# ------------------------------------------------------------------ output
def _num(v):
    try: f = float(v)
    except (TypeError, ValueError): return None
    return None if math.isnan(f) or math.isinf(f) else round(f, 2)

def build_item(sym, direction, r, frame, tfs, bars, label=None):
    d = frame.tail(bars); fmt = '%Y-%m-%d' if tfs[0] == '1D' else '%d %b %H:%M'
    it = {k: _num(r.get(k)) for k in ('price', 'zone_bot', 'zone_top', 'entry', 'sl', 't1', 't2', 't3', 'r_t1', 'risk_pct', 'rvol', 'fib_lo', 'fib_hi', 'ob_low', 'ob_high', 'fvg_low', 'fvg_high')}
    it.update(symbol=sym, direction=direction, label=label or direction.upper(), grade=r['grade'], score=int(r['score']), status=r['status'], structure=int(r['structure']), zone_q=int(r['zone_q']),
              confirm=int(r['confirm']), context=int(r['context']), ticks=[t for t in r['ticks'].split(', ') if t and t != '-'], notes=[n for n in r['notes'].split('; ') if n],
              choch_date=r['choch_date'][:10] if tfs[0] == '1D' else r['choch_date'], bos_date=r['bos_date'][:10] if tfs[0] == '1D' else r['bos_date'], tf_structure=tfs[0], tf_trigger=tfs[1],
              times=[x.strftime(fmt) for x in d.index], candles=[[round(float(x), 2) for x in row] for row in d[['Open', 'High', 'Low', 'Close']].values],
              ema=[round(float(x), 2) for x in ema(frame.Close, 9).tail(bars).values])
    return it

def write_json(out_dir, name, payload):
    os.makedirs(out_dir, exist_ok=True); path = os.path.join(out_dir, name)
    with open(path, 'w') as f: json.dump(payload, f, separators=(',', ':'))
    print(f'saved {path}'); return path

def meta(mode, now, universe, scanned, failed, note, setups, **extra):
    return dict(mode=mode, generated_at=now.isoformat(timespec='seconds'), market_open=market_open(now), universe=universe, scanned=scanned, failed=failed[:40], note=note, setups=setups, **extra)

# ------------------------------------------------------------------ runs
def run_swing(args, now):
    syms, note = load_nifty500(args.universe_csv or 'nifty500.csv', args.watchlist)
    print(f'swing: {note}'); daily, failed = download_many(syms, '1y', '1d'); daily = {s: tidy_daily(f, now) for s, f in daily.items()}
    if not daily: print('No data downloaded (Yahoo blocked or offline). Nothing written.', file=sys.stderr); sys.exit(2)
    nd, _ = download_many(['^NSEI'], '1y', '1d'); nifty = tidy_daily(nd['^NSEI'], now) if '^NSEI' in nd else None; n_up = index_ok(nifty)
    extra = lambda f: (['weekly trend'] if weekly_ok(f) else []) + (['Nifty trend'] if n_up else [])
    cand, turnover = {}, {}
    for s, f in daily.items():
        if len(f) >= CFG['min_bars']: turnover[s] = float((f.Close * f.Volume).tail(20).mean() / 1e7)
        r = scan_symbol(f, None, 'long', CFG, extra(f))
        if r and 'zone_bot' in r: cand[s] = r
    liq = [s for s, _ in sorted(turnover.items(), key=lambda kv: -kv[1])[:args.intraday_top]]
    write_json(args.out, 'liquid.json', dict(generated_at=now.isoformat(timespec='seconds'), top=liq))
    hourly, _ = download_many(list(cand), '3mo', '1h') if cand else ({}, [])
    rows = []
    for s in cand:
        h = tidy_intraday(hourly[s], now, 60) if s in hourly else None
        r = scan_symbol(daily[s], h, 'long', CFG, extra(daily[s]))
        if r and 'zone_bot' in r and r['score'] >= args.min_score: rows.append(build_item(s, 'long', r, daily[s], ('1D', '1H'), 70))
    rows.sort(key=lambda it: (-it['score'], 0 if it['status'].startswith('TRIGGER') else 1)); rows = rows[:args.top]
    write_json(args.out, 'swing.json', meta('swing', now, len(syms), len(daily), failed, note, rows, nifty_trend=bool(n_up)))
    return rows

def snapshot(df5, df15, hv):
    last = df5.iloc[-1]; day = df5[df5.index.normalize() == df5.index[-1].normalize()]
    prev = df5[df5.index.normalize() < df5.index[-1].normalize()]
    chg = (last.Close / prev.Close.iloc[-1] - 1) * 100 if len(prev) else None
    return dict(spot=_num(last.Close), change_pct=_num(chg), day_high=_num(day.High.max()), day_low=_num(day.Low.min()),
                above_5m=bool(last.Close > ema(df5.Close, 9).iloc[-1]), above_15m=bool(df15 is not None and df15.Close.iloc[-1] > ema(df15.Close, 9).iloc[-1]),
                ema_5m=_num(ema(df5.Close, 9).iloc[-1]), ema_15m=_num(ema(df15.Close, 9).iloc[-1]) if df15 is not None else None,
                pdh_pdl=[_num(x) for x in prev_day_levels(df5)], volume_available=hv, bias_up=has_bias(df15),
                bias_down=has_bias(invert(df15, float(2 * df15.High.max()))) if df15 is not None else False)

REASON = {'FAR': 'Price is far from the zone: wait for a pullback.', 'STALE': 'The structure is old.', 'WIDE': 'The zone is too tall for a sensible stop.', 'BROKEN': 'The zone was broken.',
          'EXTENDED': 'The trigger fired but price has already run away from the zone.', 'NO_BIAS': 'The 15m does not agree.', None: 'No CHoCH + BOS found on the 5m.'}

def run_options(args, now):
    d5, f5 = download_many(['^NSEI'], '5d', '5m'); d15, _ = download_many(['^NSEI'], '10d', '15m')
    if '^NSEI' not in d5 or '^NSEI' not in d15: print('No Nifty data downloaded. Nothing written.', file=sys.stderr); sys.exit(2)
    df5 = tidy_intraday(d5['^NSEI'], now, 5); df15 = tidy_intraday(d15['^NSEI'], now, 15); hv = has_volume(df5); lv = prev_day_levels(df5)
    rows, why = [], {}
    for side, label in (('long', 'CALL'), ('short', 'PUT')):
        r = scan_intraday(df5, df15, side, CFG_I, hv, lv, section='options')
        if r and 'zone_bot' in r and r['score'] >= args.min_score: rows.append(build_item('NIFTY 50', side, r, df5, ('5m', '5m'), 90, label))
        else: why[label] = REASON.get((r or {}).get('state'), 'No setup.')
    snap = snapshot(df5, df15, hv); snap['why_none'] = why
    write_json(args.out, 'options.json', meta('options', now, 1, 1, [], 'Nifty 50 index only', rows, snapshot=snap, session_date=str(df5.index[-1].date())))
    return rows

def run_intraday(args, now):
    path = os.path.join(args.out, 'liquid.json')
    try: syms = json.load(open(path))['top'][:args.intraday_top]; note = f'Most liquid {len(syms)} of the Nifty 500 (from the last swing scan)'
    except Exception:
        syms = [x.strip() for x in open(args.watchlist) if x.strip() and not x.startswith('#')][:args.intraday_top]; note = f'Starter list of {len(syms)} (run the swing scan once to rank the Nifty 500 by liquidity)'
    d5, failed = download_many(syms, '5d', '5m'); d15, _ = download_many(list(d5), '10d', '15m')
    if not d5: print('No data downloaded. Nothing written.', file=sys.stderr); sys.exit(2)
    rows = []
    for s, f in d5.items():
        f5 = tidy_intraday(f, now, 5); f15 = tidy_intraday(d15[s], now, 15) if s in d15 else None
        if f15 is None or len(f5) < CFG_I['min_bars'] or not has_volume(f5): continue
        for side in ('long', 'short'):
            try: r = scan_intraday(f5, f15, side, CFG_I, True, prev_day_levels(f5))
            except Exception as ex: print(f'  error {s}: {ex}', file=sys.stderr); continue
            if r and 'zone_bot' in r and r['score'] >= args.min_score: rows.append(build_item(s, side, r, f5, ('5m', '5m'), 90))
    rows.sort(key=lambda it: (-it['score'], 0 if it['status'].startswith('TRIGGER') else 1)); rows = rows[:args.top]
    write_json(args.out, 'intraday.json', meta('intraday', now, len(syms), len(d5), failed, note, rows))
    return rows

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mode', choices=['swing', 'options', 'intraday', 'live', 'all'], default='swing')
    p.add_argument('--out', default='_site/data'); p.add_argument('--watchlist', default='watchlist.txt'); p.add_argument('--universe-csv', default=None)
    p.add_argument('--min-score', type=int, default=4); p.add_argument('--top', type=int, default=60); p.add_argument('--intraday-top', type=int, default=100)
    args = p.parse_args(); now = pd.Timestamp.now(tz=IST)
    modes = {'swing': ['swing'], 'options': ['options'], 'intraday': ['intraday'], 'all': ['swing', 'options', 'intraday']}.get(args.mode)
    if args.mode == 'live': modes = ['options'] + (['intraday'] if now.minute % 30 < 15 else [])      # stocks every 30 minutes, Nifty every 15
    for m in modes: {'swing': run_swing, 'options': run_options, 'intraday': run_intraday}[m](args, now)

if __name__ == '__main__':
    main()
