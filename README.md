# DownerStuffScreener

A rule-book scanner for Indian markets. It runs in the cloud (GitHub Actions) and you read it on your iPhone or laptop.

## Pages
| Page | What it does |
|---|---|
| **Overview** | Market regime, today's event risks, top setups from every section, headlines |
| **Swing** | Nifty 500, **long only**. 1D CHoCH + BOS, FVG + OB zone, 1H trigger, **sector index must not be falling** |
| **Options** | Nifty 50 index only, calls and puts. 15m **CHoCH only**, 5m CHoCH + BOS, 5m trigger. **No volume rule.** Strike picked with Greeks, OI panel |
| **Intraday** | Most liquid Nifty 500 stocks, long and short. 15m **CHoCH only**, 5m CHoCH + BOS, 5m trigger with volume |
| **Market** | Trending, range-bound or volatile (daily and today), VIX-implied move, breadth, sector strength, and which setups to prefer |
| **News** | Headlines (RBI, Fed/global, crude, flows, results, policy), expiry days, holidays, policy meetings, results dates of your setups |
| **Trade** (tap any row) | Chart with entry, stop-loss, T1 to T3 and the entry zone marked, how to execute, how to trail, position size, why the trade qualifies, strike and Greeks (options), news for that stock |

## Rules by section
| | Swing | Options | Intraday |
|---|---|---|---|
| Bias | Weekly trend and Nifty trend (info) | 15m CHoCH, still intact | 15m CHoCH, still intact |
| Structure and zone | 1D CHoCH + BOS, FVG + OB | 5m CHoCH + BOS, FVG + OB | 5m CHoCH + BOS, FVG + OB |
| Trigger | 1H rejection, 9 EMA close, volume 1.5x **for the same time of day** | 5m rejection, 9 EMA close | 5m rejection, 9 EMA close, volume 1.5x |
| Score | Structure 2, Zone 2, Confirmation 3, Context 3 | Structure 2, Zone 2, Confirmation 2, Context 4 | Structure 2, Zone 2, Confirmation 3, Context 3 |
| Confluences | key level, fib, MTF EMA, weekly trend, Nifty trend | key level, fib, MTF EMA, **15m order block, OI wall** | key level, fib, MTF EMA |
| Side | Long only | Calls and puts | Long and short |

Grades: 8 to 10 A+, 6 to 7 A, 4 to 5 B (observe). The stop is below the order block with a 0.25 ATR buffer and is never widened.

## Sector index confirmation (swing)
A long must not be going against its own index. Each stock with a setup is mapped to its NSE index from the Nifty 500 industry (Bank Nifty and Nifty PSU Bank for banks, Nifty IT, Auto, Pharma, FMCG, Metal, Realty, Energy, Media, Infra, Financial Services). Industries with no index of their own, or an index Yahoo does not return, use an equal-weight basket of the Nifty 500 stocks in the same industry. The index is **falling** if it is more than half an ATR under its 21 EMA, or under its 9 EMA with a falling 21 EMA, or down 3% in 5 days, or down 1% today. A falling index turns a TRIGGERED long into **WATCH (index falling)** (no alert) until it stabilises, and the trade page explains why. The trail plan also sells half if the sector index closes under its 21 EMA.

## India-specific refinements (swing and everywhere)
- Prices are rounded to the NSE tick of 5 paise.
- Volume on the 1H candle is compared with the same time-of-day candle of earlier days (the 09:15 candle is always heavy, so the whole-day average flattered it).
- Stocks with a locked (zero-range) session in the last 5 days are skipped: you cannot exit a locked circuit.
- Sector strength and relative strength vs Nifty (20 days) from the Nifty 500 industries are shown with every stock.
- Results date (Yahoo, when it has one) is flagged. Exit or cut size before results.
- Weekly Nifty expiry is Tuesday (the previous trading day when Tuesday is a holiday), lot size 65. Holidays are in `events.json`.
- Execution notes use GTT/OCO for delivery, MIS with SL-M for intraday, and the 15:10 square-off.

## Option strike selection
Theoretical Black-Scholes prices with India VIX as the volatility. For the setup's entry, stop and targets it re-prices five strikes at the stop and at T1, T2, T3 (after the time you would plausibly hold) and picks the best premium reward-to-risk with delta in 0.40 to 0.60 (0.50 to 0.70 late in the day or when the expiry is under 3 days away). You see delta, gamma, theta (per day and per hour), vega, premium at SL and each target. If the nearest weekly expiry is under 2 days away it uses the next one. These are model prices: always compare with the live option chain.

## Open interest
The scanner asks NSE for the option chain. NSE often blocks cloud servers, so this is best effort. When it works the OI panel shows the call wall, put wall, PCR and max pain, and OI becomes a confluence tick. When it does not, type the walls from your own chain into the OI panel: the verdict updates instantly and is remembered on your phone.

## Update your repo (GitHub website only)
1. Repo > **Add file** > **Upload files**. Drag in everything from this folder: the `.py` files (including the new `sector_index.py`), `events.json`, `requirements.txt`, `watchlist.txt` and the whole `site` folder. Commit. Same-named files are replaced.
2. Delete `test_fetch.py` if it is still in the repo (it tests an older version).
3. Open `.github/workflows/scan.yml`, click the pencil, replace everything with the new `scan.yml`, commit.
4. Your secret `NTFY_TOPIC` and variable `PAGE_URL` stay as they are.
5. Actions > **scan** > **Run workflow** > mode **all**. The first full run takes a few minutes.

## Files you will edit most
- `strategy_scanner.py`: the `CFG`, `CFG_I` and `CFG_B` blocks hold the rule thresholds.
- `events.json`: holidays and macro events. Add your own.
- `watchlist.txt`: fallback list. Put a `nifty500.csv` in the repo root for the full list with industries.
- `site/ds.css` and `site/ds.js`: the look and the pages.

## Schedule (IST, Monday to Friday) and what updates when
| What | How often | Cron (UTC) |
|---|---|---|
| **Nifty options** page (chart, levels, strike, OI) | every 5 minutes, 09:17 to 15:32 | `47-57/5 3`, `2-59/5 4-9`, `2 10` |
| **Intraday** page (liquid stocks) | every 5 minutes, same runs | same |
| Market regime | every 5 minutes, same runs | same |
| **Swing** page (Nifty 500, sector index check, chart with today's candle) | every hour at about :25, after each 1H candle has closed, plus 08:37 and 16:17 | `55 4-9`, `7 3`, `47 10` |
| News and events | about every 30 minutes | with the 5-minute runs |

Notes: 5 minutes is the fastest schedule GitHub allows. GitHub often starts scheduled runs late (5 to 30 minutes at busy times), and the minutes are offset (:02, :07 ...) to avoid its busiest moments. Runs go one at a time, so while the hourly swing scan runs (a few minutes) the 5-minute runs wait. The 15m candles of the intraday stocks are downloaded only when a new 15-minute candle has closed. The pages re-read the data every minute while the market is open, and the "Updated ... min ago" pill turns red if a section is stale. The hourly swing run also adds today's candle to the swing chart from the closed 1H candles, and the LTP is the latest closed 1H close. After 60 days without a commit GitHub pauses scheduled runs: click Enable on the Actions tab.

Phone alerts: a triggered setup is pushed straight away. "Scan updated" pushes now default to the hourly swing scans only (`NTFY_UPDATES` = `swing`); set the repo variable to `all` for every scan or `off` for none.

## Limits
- Yahoo Finance data is unofficial and can be delayed; 500 symbols can be rate-limited. A failed run keeps the last good page.
- The index has no volume feed here. The options rules do not use volume at all.
- Futures OI, results dates, sector news and the live option premium are not guaranteed: check them.
- A scan finds candidates by rules. It is not a trade signal and not investment advice.

## Tests (no internet needed)
`python test_scanner.py`, `test_data.py`, `test_greeks.py`, `test_oi.py`, `test_market.py`, `test_news.py`, `test_sector.py`, `test_pipeline.py`
