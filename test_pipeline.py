"""End-to-end test of all three sections and the phone alerts, with fake downloads. Run: python test_pipeline.py"""
import http.server, json, os, subprocess, sys, tempfile, threading
import numpy as np, pandas as pd
sys.argv = ['x']
src = open('test_scanner.py').read().split("CFG = dict(sc.CFG")[0]; ns = {}; exec(src, ns)
sc, D, H, flip = ns['sc'], ns['D'], ns['H'], ns['flip']
sc.CFG.update(min_turnover_cr=0, min_price=0, min_bars=30, rvol_n=10); sc.CFG_I.update(min_bars=30, rvol_n=10, max_zone_pct=6, max_zone_atr=5)
tz = 'Asia/Kolkata'; n5 = len(D) + len(H); bias_rows = D + D
idx5 = pd.date_range('2026-10-12 09:15', periods=n5, freq='5min', tz=tz); idx15 = pd.date_range('2026-10-08 09:15', periods=len(bias_rows), freq='15min', tz=tz)
mk = lambda rows, idx: pd.DataFrame(rows, columns=sc.COLS, index=idx)
rnd = lambda n, idx, seed: (lambda r: pd.DataFrame({'Open': (c := 500 + np.cumsum(r.normal(0, 1, n))), 'High': c + 2, 'Low': c - 2, 'Close': c, 'Volume': r.integers(1e4, 9e4, n)}, index=idx))(np.random.default_rng(seed))
daily_idx = pd.bdate_range('2026-01-01', periods=len(D))
FR = {
  '1d': {'AAA': mk(D, daily_idx), 'BBB': mk(D, daily_idx), 'CCC': rnd(len(D), daily_idx, 1), 'DDD': mk(flip(D), daily_idx), '^NSEI': rnd(len(D), daily_idx, 2)},
  '1h': {'AAA': mk(H, pd.date_range('2026-02-04 03:45', periods=len(H), freq='h', tz='UTC')), 'BBB': mk(H[:14], pd.date_range('2026-02-04 03:45', periods=14, freq='h', tz='UTC'))},
  '5m': {'AAA': mk(D + H, idx5), 'BBB': mk(flip(D + H), idx5), 'CCC': rnd(n5, idx5, 3), 'DDD': rnd(n5, idx5, 4), '^NSEI': mk(D + H, idx5).assign(Volume=0)},
  '15m': {'AAA': mk(bias_rows, idx15), 'BBB': mk(flip(bias_rows), idx15), 'CCC': rnd(len(bias_rows), idx15, 5), 'DDD': rnd(len(bias_rows), idx15, 6), '^NSEI': mk(bias_rows, idx15)}}
def fake_download(symbols, period, interval, chunk=50, pause=1.0):
    out = {s: FR[interval][s].copy() for s in symbols if s in FR[interval]}; return out, [s for s in symbols if s not in out]
sc.download_many = fake_download; sc.load_nifty500 = lambda *a, **k: (['AAA', 'BBB', 'CCC', 'DDD'], 'test universe (4 symbols)')

out = os.environ.get('OUT_DIR') or tempfile.mkdtemp(); sys.argv = ['x', '--mode', 'all', '--out', out, '--min-score', '4']; sc.main()
fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'   {info}' if info else ''))
    if not cond: fails.append(name)
J = lambda n: json.load(open(os.path.join(out, n + '.json')))
sw, op, it, lq = J('swing'), J('options'), J('intraday'), J('liquid')
check('all four files are written', all(os.path.exists(os.path.join(out, f)) for f in ('swing.json', 'options.json', 'intraday.json', 'liquid.json')))
check('swing: long only, even though a bearish stock is in the universe', sw['setups'] and all(s['direction'] == 'long' for s in sw['setups']) and 'DDD' not in [s['symbol'] for s in sw['setups']], str([(s['symbol'], s['direction'], s['status']) for s in sw['setups']]))
check('swing: AAA triggered, BBB waiting for the 1H trigger', {s['symbol']: s['status'] for s in sw['setups']}.get('AAA') == 'TRIGGERED' and {s['symbol']: s['status'] for s in sw['setups']}.get('BBB', '').startswith('WATCH'))
check('swing: carries universe note, daily candles and tags', sw['universe'] == 4 and 'test universe' in sw['note'] and sw['setups'][0]['tf_structure'] == '1D' and sw['setups'][0]['tf_trigger'] == '1H' and len(sw['setups'][0]['candles']) == len(D) and len(sw['setups'][0]['times'][0]) == 10)
check('liquid list ranks stocks for the intraday scan', set(lq['top']) >= {'AAA', 'BBB'})
check('options: a CALL with the volume warning, no PUT', [s['label'] for s in op['setups']] == ['CALL'] and op['setups'][0]['status'] == 'TRIGGER (check volume)' and 'PUT' in op['snapshot']['why_none'], str(op['snapshot']['why_none']))
check('options: snapshot for the page', all(k in op['snapshot'] for k in ('spot', 'above_5m', 'above_15m', 'ema_5m', 'ema_15m', 'pdh_pdl', 'volume_available', 'bias_up', 'bias_down')) and op['snapshot']['volume_available'] is False and op['snapshot']['bias_up'] is True)
check('intraday: AAA long and BBB short, on the 5m', {(s['symbol'], s['direction']) for s in it['setups']} >= {('AAA', 'long'), ('BBB', 'short')} and it['setups'][0]['tf_structure'] == '5m', str([(s['symbol'], s['direction'], s['status']) for s in it['setups']]))
check('intraday: only the most liquid stocks are scanned', it['universe'] == len(lq['top']) and 'liquid' in it['note'].lower())
check('every setup has levels, ticks and candles for the chart', all(s['entry'] and s['sl'] and s['t1'] and s['candles'] and s['ema'] and isinstance(s['ticks'], list) for f in (sw, op, it) for s in f['setups']))

# phone alerts across the three sections
got = []
class Hd(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0)); got.append((self.path, dict(self.headers), self.rfile.read(n).decode('utf-8'))); self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def log_message(self, *a): pass
srv = http.server.HTTPServer(('127.0.0.1', 0), Hd); threading.Thread(target=srv.serve_forever, daemon=True).start()
state = os.path.join(tempfile.mkdtemp(), 'n.json')
env = dict(os.environ, NTFY_TOPIC='secret-topic', NTFY_URL=f'http://127.0.0.1:{srv.server_port}', NTFY_MIN_SCORE='6', PAGE_URL='https://x.github.io/r/')
run = lambda: subprocess.run([sys.executable, 'notify.py', '--dir', out, '--state', state], env=env, capture_output=True, text=True).stdout.strip()
o1 = run(); titles = [g[1]['Title'] for g in got]
check('alerts: triggers from all sections are pushed, watch setups are not', len(got) >= 3 and any(t.startswith('Swing') for t in titles) and any(t.startswith('Nifty options') and 'CALL' in t for t in titles) and any(t.startswith('Intraday') for t in titles) and not any('WATCH' in t for t in titles), str(titles))
check('alerts: titles are ASCII and the click link is set', all(t.isascii() for t in titles) and got[0][1].get('Click') == 'https://x.github.io/r/')
n = len(got); o2 = run()
check('alerts: nothing is sent twice in a day', len(got) == n and 'alerts sent: 0' in o2, o2)
env.pop('NTFY_TOPIC'); check('alerts: no topic -> skipped quietly', 'skipping' in run())
print('\nALL PASSED' if not fails else f'\n{len(fails)} FAILED: {fails}')
sys.exit(1 if fails else 0)
