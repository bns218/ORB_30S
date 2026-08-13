# ORB_30S — F&O 30-Second Candle Gainers/Losers Dashboard

Live dashboard that streams NSE F&O equity ticks over AngelOne SmartAPI's
WebSocket2.0 feed, builds rolling 30-second OHLC candles per symbol, and
flags **GAINER** / **LOSER** signals based on candle shape:

- **GAINER** — two consecutive 30s candles that open low, run up, and close
  at/near the high (strong green candles back to back).
- **LOSER** — two consecutive 30s candles that open high, run down, and
  close at/near the low (strong red candles back to back).

Ticks are aggregated in-process (no external DB) and pushed to the browser
over a WebSocket every second.

## How it works

```
AngelOne SmartAPI WebSocket2.0  →  app/feed.py     (subscribes ~208 F&O stocks)
                                        │  ticks
                                        ▼
                                  app/candles.py    (30s OHLC + GAINER/LOSER logic)
                                        │  snapshot every 1s
                                        ▼
                                  app/server.py     (FastAPI, broadcasts over /ws)
                                        │
                                        ▼
                                  static/           (browser dashboard)
```

## Requirements

- Python 3.11+
- An AngelOne SmartAPI account with:
  - An API app created at https://smartapi.angelbroking.com/apps (gives you `SMARTAPI_API_KEY`)
  - Your trading client code and password
  - TOTP enabled on the account, with the **base32 secret** (not a 6-digit code) shown when you set it up

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your credentials:

   ```bash
   cp .env.example .env
   ```

   ```
   SMARTAPI_API_KEY=your_api_key
   SMARTAPI_CLIENT_CODE=your_client_code
   SMARTAPI_PASSWORD=your_login_password
   SMARTAPI_TOTP_SECRET=your_base32_totp_secret
   ```

   `.env` is gitignored — never commit real credentials.

## Run

```bash
python run.py
```

This logs in to SmartAPI, opens the WebSocket feed, subscribes to the F&O
stock list in `data/fo_stocks.json`, and starts the dashboard server.

Open **http://localhost:8000** in a browser.

The status badge in the top right shows `live` when the WebSocket feed is
connected and streaming.

## Notes

- Only works with live/streaming data during NSE market hours
  (9:15 AM – 3:30 PM IST). Outside market hours the feed connects but no
  new ticks arrive, so candles won't advance.
- The tracked symbol list (`data/fo_stocks.json`) is the current NSE F&O
  equity list with exchange/token metadata; edit it to track a different
  set of symbols.
- `GET /api/snapshot` returns the current state as JSON if you want to poll
  instead of using the WebSocket.

## Project layout

```
app/
  auth.py      SmartAPI login (API key + client code + password + TOTP)
  feed.py      SmartWebSocketV2 wrapper: subscribes symbols, dispatches ticks
  candles.py   30s OHLC aggregation + GAINER/LOSER classification
  server.py    FastAPI app: serves the dashboard, broadcasts snapshots over /ws
data/
  fo_stocks.json   Tracked F&O symbol list (symbol -> exchange/token)
static/
  index.html, app.js, style.css   Dashboard UI
run.py         Entrypoint (uvicorn)
```
