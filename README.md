# Setup Radar: Nifty 500 swing, Nifty options and intraday scanner

One web page with three sections, scanned in the cloud (GitHub Actions) and read on your iPhone:

| Section | Universe | Timeframes | Side |
|---|---|---|---|
| Swing | Nifty 500 | 1D structure, 1H trigger | Long only |
| Nifty options | Nifty 50 index only | 15m bias, 5m structure and trigger | Calls and puts |
| Intraday | The 100 most liquid Nifty 500 stocks | 15m bias, 5m structure and trigger | Long and short |

Every section runs your rule book: CHoCH, then BOS with displacement, then FVG + order block, pullback into the zone, rejection, a close back through the 9 EMA on volume at least 1.5x, a structural stop below the order block, and your 10-point scorecard with the confluence ticks.

## Update your existing repo (GitHub website only)
1. Repo > **Add file** > **Upload files**. Drag in these files from the unzipped folder and commit. Same-named files are replaced: `strategy_scanner.py`, `notify.py`, `requirements.txt`, `watchlist.txt`, `test_scanner.py`, `test_data.py`, `test_pipeline.py`, and the `site` folder (`index.html`, `manifest.webmanifest`, three icons).
2. Delete the old `test_fetch.py` (open it, click the bin icon, commit). It tests the old code.
3. Replace the workflow: open `.github/workflows/scan.yml`, click the pencil, select all, paste the contents of the new `scan.yml`, commit.
4. Your secret `NTFY_TOPIC` and variable `PAGE_URL` stay as they are.
5. Actions > **scan** > **Run workflow** > mode **all** > Run. The first full run takes a few minutes. Then open your page.

## The Nifty 500 list
Each swing run downloads the current list from NSE Indices. If that is blocked, it uses a `nifty500.csv` in your repo, and if neither works it falls back to the short `watchlist.txt` and says so on the page ("Fallback list of ... symbols"). For a reliable backup, download the CSV in your browser from https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv and upload it to the repo root as `nifty500.csv` (keep the Symbol column).

## Schedule (IST, Monday to Friday)
| Time | What runs |
|---|---|
| 08:30 | Swing, before the open |
| 10:35, 11:35, 12:35, 13:35, 14:35 | Swing 1H triggers, 20 minutes after each 1H close |
| 16:15 | Swing, after the close |
| 09:30 to 15:15, every 15 minutes | Nifty options. Intraday stocks run every second slot (every 30 minutes) |

Each run refreshes only its own section and keeps the others. GitHub can start scheduled runs late, especially the 15-minute ones. To reduce load, edit the `cron` lines. The intraday stock count is `--intraday-top` (default 100).

## What the page shows
- **Desktop:** three columns side by side with a sidebar in the Trade Insight style. **iPhone:** a tab bar (Swing, Options, Intraday, Rule book).
- Each card shows zone, entry, SL, T1 with R, and ticks. Tap it for the chart, structure dates, volume, and a quantity calculator (stocks) or the premium-risk estimate (Nifty).
- Nifty options also shows a snapshot: spot, 15m bias, 5m and 15m EMA position, previous-day high and low.
- Alerts (ntfy) push new TRIGGER setups from all three sections, once per setup per day.

## Limits to know
- **Index volume:** Yahoo has no usable volume for the Nifty index, so the options section shows "TRIGGER (check volume)". Check NIFTY1! volume yourself. OI is manual too.
- **Yahoo Finance data:** it is unofficial, can be delayed about 15 minutes, and may rate-limit 500 symbols. A failed run keeps the last good page. A broker API is the dependable fix.
- **Rules, not judgement:** the scan finds candidates by rules. Futures OI, results date, sector strength and news are not checked. Not a trade signal and not investment advice.

## Tests
`python test_scanner.py` (rules), `python test_data.py` (downloads, Nifty 500 list), `python test_pipeline.py` (all three sections and alerts). They need no internet.
