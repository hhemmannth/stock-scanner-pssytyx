"""Rule-engine tests on synthetic setups with clear swings. Run: python test_scanner.py"""
import sys
import numpy as np, pandas as pd
import strategy_scanner as sc

closes = [1115,1117,1118,1119,1119,1120,1112,1103,1094,1085,1088,1093,1097,1100,1090,1079,1069,1062,1067,1072,1076,1080,1071,1060,1049,1040,
          1047,1056,1065,1074,1090,1084,1078,1112,1122,1130,1122,1114,1106,1100,1096,1094]
wick_up = {5: 5, 13: 5, 21: 5}; wick_dn = {9: 5, 17: 5, 25: 5}; vols = {30: 190, 33: 220, 25: 200}
def daily_rows():
    rows = []; prev = 1114
    for i, c in enumerate(closes):
        o = prev; h = max(o, c) + wick_up.get(i, 2); l = min(o, c) - wick_dn.get(i, 2)
        if i == 25: l = 1028
        rows.append([o, h, l, c, vols.get(i, 100)]); prev = c
    return rows
D = daily_rows()
h1c = [1122,1120,1123,1116,1112,1115,1108,1104,1107,1100,1096,1099,1094,1090,1093,1088,1094,1096,1093,1092,1101,1103]
def hourly_rows():
    rows = []; prev = 1124
    for i, c in enumerate(h1c):
        o = prev; h = max(o, c) + 3; l = min(o, c) - 3
        if i == 15: l = 1083
        rows.append([o, h, l, c, 175 if i == 20 else 100 + (i % 4) * 5]); prev = c
    return rows
H = hourly_rows()
def frame(rows, freq, tz=None):
    return pd.DataFrame(rows, columns=sc.COLS, index=pd.date_range('2026-01-01', periods=len(rows), freq=freq, tz=tz))
flip = lambda rows: [[2300 - a, 2300 - c_, 2300 - b, 2300 - d_, v] for a, b, c_, d_, v in rows]

CFG = dict(sc.CFG, pivot=3, min_turnover_cr=0, min_price=0, min_bars=30, rvol_n=10)
CFG5 = dict(sc.CFG_I, min_turnover_cr=0, min_bars=30, rvol_n=10, max_zone_pct=6, max_zone_atr=5)
fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'   {info}' if info else ''))
    if not cond: fails.append(name)
h = [r[1] for r in D]; l = [r[2] for r in D]; o = [r[0] for r in D]
daily = frame(D, 'D'); hourly = frame(H, 'h', 'Asia/Kolkata')

print('--- swing (1D structure, 1H trigger, long only) ---')
r = sc.scan_symbol(daily, hourly, 'long', CFG, ['weekly trend', 'Nifty trend'])
check('long setup found', r is not None and 'zone_bot' in r, str(r and r.get('state')))
if r and 'zone_bot' in r:
    check('CHoCH on bar 30 above the lower high', r['choch_date'].startswith(str(daily.index[30])[:10]) and abs(r['choch_level'] - h[21]) < .01, r['choch_date'])
    check('BOS on bar 33', r['bos_date'].startswith(str(daily.index[33])[:10]), r['bos_date'])
    check('OB = last down candle before the BOS', abs(r['ob_low'] - l[32]) < .01 and abs(r['ob_high'] - o[32]) < .01, f"{r['ob_low']}-{r['ob_high']}")
    check('FVG = gap between bar 32 high and bar 34 low', abs(r['fvg_low'] - h[32]) < .01 and abs(r['fvg_high'] - l[34]) < .01, f"{r['fvg_low']}-{r['fvg_high']}")
    rng = max(h[33:]) - l[32]
    check('fib 0.618-0.705 of the leg', abs(r['fib_hi'] - (max(h[33:]) - .618 * rng)) < .01 and abs(r['fib_lo'] - (max(h[33:]) - .705 * rng)) < .01)
    check('in the zone and TRIGGERED', r['state'] == 'IN_ZONE' and r['status'] == 'TRIGGERED', f"{r['state']} / {r['status']}")
    check('confirmation 3/3 and ticks counted', r['confirm'] == 3 and all(t in r['ticks'] for t in ['key level', 'fib', 'MTF EMA', 'weekly trend']), r['ticks'])
    check('score 10 = A+ (context capped at 3)', r['score'] == 10 and r['grade'] == 'A+', f"{r['score']} {r['grade']}")
    check('SL below the OB and T2 = 2R', r['sl'] < r['ob_low'] and abs((r['t2'] - r['entry']) - 2 * (r['entry'] - r['sl'])) < .01, f"entry {r['entry']:.1f} sl {r['sl']:.1f} r_t1 {r['r_t1']:.2f}")
try: sc.scan_symbol(daily, hourly, 'short', CFG); refused = False
except ValueError: refused = True
check('swing refuses short (rule book: long only)', refused)
r2 = sc.scan_symbol(daily, frame(H[:14], 'h', 'Asia/Kolkata'), 'long', CFG)
check('no 1H trigger yet -> WATCH or APPROACHING', r2 is not None and 'zone_bot' in r2 and not r2['status'].startswith('TRIGGER'), str(r2 and r2.get('status')))
r3 = sc.scan_symbol(frame(D[:36], 'D'), None, 'long', CFG)
check('just above the zone -> APPROACHING', r3 is not None and r3['status'].startswith('APPROACHING'), str(r3 and r3.get('status')))
r3b = sc.scan_symbol(frame(D[:36] + [[1130, 1160, 1128, 1156, 100]], 'D'), None, 'long', CFG)
check('far above the zone is not reported', r3b is None or 'zone_bot' not in r3b, str(r3b and r3b.get('state')))
r4 = sc.scan_symbol(frame(D + [[1094, 1095, 1040, 1048, 200]], 'D'), None, 'long', CFG)
check('a close below the zone cancels it', r4 is None or 'zone_bot' not in r4, str(r4 and r4.get('state')))
try: r9 = sc.scan_symbol(frame(D[:34], 'D'), None, 'long', CFG); ok9 = True
except Exception as ex: ok9 = False; r9 = str(ex)
check('BOS on the very last bar does not crash', ok9, str(r9 if not ok9 else ''))
check('old structure ignored (max_bos_age)', (lambda x: x is None or 'zone_bot' not in x)(sc.scan_symbol(daily, hourly, 'long', dict(CFG, max_bos_age=5))))
check('tall zone ignored (max_zone_atr)', (lambda x: x is None or 'zone_bot' not in x)(sc.scan_symbol(daily, hourly, 'long', dict(CFG, max_zone_atr=1.0))))
runaway = frame(H[:20] + [[1093, 1170, 1090, 1160, 175]], 'h', 'Asia/Kolkata')
check('a trigger after price ran away is dropped', (lambda x: x is None or 'zone_bot' not in x)(sc.scan_symbol(daily, runaway, 'long', CFG)))
lowvol = [row[:] for row in H]; lowvol[20][4] = 95
r8 = sc.scan_symbol(daily, frame(lowvol, 'h', 'Asia/Kolkata'), 'long', CFG)
check('trigger without volume is only WATCH', r8 is not None and r8['status'].startswith('WATCH (trigger'), str(r8 and r8.get('status')))
check('weekly trend helper', sc.weekly_ok(pd.DataFrame({'Close': np.linspace(100, 200, 120)}, index=pd.bdate_range('2026-01-01', periods=120))) and not sc.weekly_ok(pd.DataFrame({'Close': np.linspace(200, 100, 120)}, index=pd.bdate_range('2026-01-01', periods=120))))

print('--- options and intraday (15m bias, 5m structure + 5m trigger) ---')
idx5 = pd.date_range('2026-10-12 09:15', periods=len(D) + len(H), freq='5min', tz='Asia/Kolkata')
f5 = pd.DataFrame(D + H, columns=sc.COLS, index=idx5)
bias_rows = D + D
f15 = pd.DataFrame(bias_rows, columns=sc.COLS, index=pd.date_range('2026-10-08 09:15', periods=len(bias_rows), freq='15min', tz='Asia/Kolkata'))
ri = sc.scan_intraday(f5, f15, 'long', CFG5, True, [], section='intraday')
check('intraday long setup found', ri is not None and 'zone_bot' in ri, str(ri and ri.get('state')))
if ri and 'zone_bot' in ri:
    check('structure 2/2 with the 15m bias', ri['structure'] == 2, str(ri['structure']))
    check('TRIGGERED with volume, score A+', ri['status'] == 'TRIGGERED' and ri['grade'] == 'A+', f"{ri['status']} {ri['score']}")
    check('SL below the zone, T2 = 2R', ri['sl'] < ri['zone_bot'] and abs((ri['t2'] - ri['entry']) - 2 * (ri['entry'] - ri['sl'])) < .01)
ro = sc.scan_intraday(f5, f15, 'long', CFG5, False, [], section='options')
check('options: no index volume -> TRIGGER (check volume)', ro is not None and ro['status'] == 'TRIGGER (check volume)' and ro['confirm'] == 2, str(ro and (ro['status'], ro['confirm'])))
check('options notes mention OI and NIFTY1! volume', ro is not None and 'futures OI' in ro['notes'] and 'NIFTY1!' in ro['notes'])
rn = sc.scan_intraday(f5, f15.iloc[:20], 'long', CFG5, True, [])
check('no 15m bias -> rejected (NO_BIAS)', rn is None or rn.get('state') == 'NO_BIAS', str(rn and rn.get('state')))
f5s = pd.DataFrame(flip(D + H), columns=sc.COLS, index=idx5); f15s = pd.DataFrame(flip(bias_rows), columns=sc.COLS, index=f15.index)
rs = sc.scan_intraday(f5s, f15s, 'short', CFG5, True, [])
check('short (put) mirrors the long setup', rs is not None and 'zone_bot' in rs and rs['grade'] == 'A+' and rs['sl'] > rs['zone_top'] and rs['t2'] < rs['entry'], str(rs and (rs.get('grade'), rs.get('state'))))
check('a long scan on mirrored data finds nothing', (lambda x: x is None or 'zone_bot' not in x)(sc.scan_intraday(f5s, f15s, 'long', CFG5, True, [])))
pl = sc.prev_day_levels(pd.DataFrame({'High': [5, 7, 6, 9], 'Low': [1, 2, 3, 4], 'Open': 1, 'Close': 1, 'Volume': 1}, index=pd.to_datetime(['2026-10-09 10:00', '2026-10-09 11:00', '2026-10-12 10:00', '2026-10-12 11:00']).tz_localize('Asia/Kolkata')))
check('previous-day high and low', pl == [7.0, 1.0], str(pl))
check('volume availability check', sc.has_volume(f5) and not sc.has_volume(f5.assign(Volume=0)))
print('\nALL PASSED' if not fails else f'\n{len(fails)} FAILED: {fails}')
sys.exit(1 if fails else 0)
