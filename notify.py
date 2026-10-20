#!/usr/bin/env python3
"""Push new TRIGGER setups from all three sections to your iPhone through ntfy (https://ntfy.sh).

Env vars:
  NTFY_TOPIC       required. A long random topic name. Anyone who knows it can read the alerts.
  NTFY_MIN_SCORE   default 6 (grade A and above)
  NTFY_STATUSES    default TRIGGER (matches TRIGGERED and TRIGGER (check volume)). Add WATCH to get those too.
  PAGE_URL         optional, opens when you tap the notification
  NTFY_URL         default https://ntfy.sh
Each setup is sent once per day (state kept in --state)."""
import argparse, datetime, json, os, sys, urllib.request

SECTIONS = [('swing', 'Swing'), ('options', 'Nifty options'), ('intraday', 'Intraday')]

def ist_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')

def fmt(v): return '-' if v is None else f'{v + 1e-9:,.1f}'

def message(s):
    lines = [f"Zone {fmt(s['zone_bot'])}-{fmt(s['zone_top'])}   Entry {fmt(s['entry'])}   SL {fmt(s['sl'])}", f"T1 {fmt(s['t1'])} ({fmt(s['r_t1'])}R)   T2 {fmt(s['t2'])}",
             'Ticks: ' + (', '.join(s['ticks']) or 'none'), ' / '.join(s['notes'][:2]) or 'Check the chart before trading.']
    return '\n'.join(lines)

def send(base, topic, s, section, click):
    what = s.get('label', s['direction'].upper())
    title = f"{section}: {s['status'].split(' ')[0]} {s['grade']} {s['symbol']} {what} ({s['score']}/10)"
    headers = {'Title': title.encode('ascii', 'ignore').decode(), 'Priority': '4' if s['grade'] == 'A+' else '3',
               'Tags': 'chart_with_upwards_trend' if s['direction'] == 'long' else 'chart_with_downwards_trend'}
    if click: headers['Click'] = click
    urllib.request.urlopen(urllib.request.Request(f'{base}/{topic}', data=message(s).encode('utf-8'), headers=headers, method='POST'), timeout=20).read()

def send_test(base, topic, click):
    headers = {'Title': 'Setup Radar: test alert', 'Priority': '3', 'Tags': 'white_check_mark'}
    if click: headers['Click'] = click
    body = 'Alerts are working. You will get a push here when a swing, Nifty options or intraday setup triggers (score 6 or more).'
    urllib.request.urlopen(urllib.request.Request(f'{base}/{topic}', data=body.encode('utf-8'), headers=headers, method='POST'), timeout=20).read()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dir', default='_site/data'); ap.add_argument('--state', default='.state/notified.json')
    ap.add_argument('--test', action='store_true', help='send one test notification and exit'); a = ap.parse_args()
    topic = os.environ.get('NTFY_TOPIC', '').strip()
    if not topic: print('NTFY_TOPIC not set, skipping alerts.'); return 1 if a.test else 0
    if a.test:
        try: send_test(os.environ.get('NTFY_URL', 'https://ntfy.sh').rstrip('/'), topic, os.environ.get('PAGE_URL', '').strip()); print('test alert sent'); return 0
        except Exception as ex: print(f'test alert failed: {ex}', file=sys.stderr); return 1
    base = os.environ.get('NTFY_URL', 'https://ntfy.sh').rstrip('/'); min_score = int(os.environ.get('NTFY_MIN_SCORE', '6') or 6)
    statuses = tuple(x.strip().upper() for x in os.environ.get('NTFY_STATUSES', 'TRIGGER').split(',') if x.strip()); click = os.environ.get('PAGE_URL', '').strip(); today = ist_today()
    try: state = json.load(open(a.state))
    except Exception: state = {}
    if state.get('date') != today: state = {'date': today, 'sent': []}
    sent = 0
    for key, title in SECTIONS:
        try: data = json.load(open(os.path.join(a.dir, key + '.json')))
        except Exception: continue
        for s in data.get('setups', []):
            k = f"{key}|{s['symbol']}|{s['direction']}|{s['bos_date']}|{s['status'].split(' ')[0]}"
            if s['score'] < min_score or not s['status'].upper().startswith(statuses) or k in state['sent']: continue
            try: send(base, topic, s, title, click); state['sent'].append(k); sent += 1
            except Exception as ex: print(f"  could not send {s['symbol']}: {ex}", file=sys.stderr)
    os.makedirs(os.path.dirname(a.state) or '.', exist_ok=True); json.dump(state, open(a.state, 'w')); print(f'alerts sent: {sent}'); return 0

if __name__ == '__main__':
    sys.exit(main())
