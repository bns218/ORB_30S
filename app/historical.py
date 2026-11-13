"""Reconstruct a GAINER/LOSER classification for a past time window using
AngelOne's historical candle API (1-minute is the finest granularity it
offers — true 30s candles cannot be recovered after the fact).

Classifies each symbol using two consecutive 1-minute candles starting at
`time_ist` and `time_ist + 1 minute`, with the same "closed near the
high/low" rule as the live 30s dashboard.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from app.auth import login
from app.candles import Candle, candle_color

RATE_LIMIT_SLEEP = 1.1  # AngelOne's real-world burst limit is tighter than the documented 3 req/sec
MAX_RETRIES = 4


def fetch_window(symbols: list[dict], date_str: str, time_ist: str) -> dict:
    """symbols: list of {symbol, tradingsymbol, symboltoken} (NSE equities).
    date_str: 'YYYY-MM-DD'. time_ist: 'HH:MM'.
    """
    session = login()
    connect = session.connect

    t0 = datetime.strptime(f"{date_str} {time_ist}", "%Y-%m-%d %H:%M")
    t0 = t0.replace(second=0, microsecond=0)
    t1 = t0 + timedelta(minutes=1)
    t2 = t0 + timedelta(minutes=2)

    fromdate = t0.strftime("%Y-%m-%d %H:%M")
    todate = t2.strftime("%Y-%m-%d %H:%M")

    gainers, losers, errors = [], [], []

    for s in symbols:
        params = {
            "exchange": "NSE",
            "symboltoken": s["symboltoken"],
            "interval": "ONE_MINUTE",
            "fromdate": fromdate,
            "todate": todate,
        }

        resp = None
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = connect.getCandleData(params)
            except Exception as e:
                last_error = str(e)
                resp = None
            if resp and resp.get("status"):
                break
            last_error = resp.get("message") if resp else last_error
            resp = None
            time.sleep(RATE_LIMIT_SLEEP * (attempt + 2))  # back off harder each retry

        if resp is None:
            errors.append({"symbol": s["symbol"], "error": last_error})
            time.sleep(RATE_LIMIT_SLEEP)
            continue

        rows = resp.get("data") or []
        # each row: [timestamp, open, high, low, close, volume]
        by_minute = {}
        for row in rows:
            ts = row[0][:16]  # 'YYYY-MM-DDTHH:MM'
            by_minute[ts] = row

        key0 = t0.strftime("%Y-%m-%dT%H:%M")
        key1 = t1.strftime("%Y-%m-%dT%H:%M")
        row0 = by_minute.get(key0)
        row1 = by_minute.get(key1)

        if row0 and row1:
            c0 = Candle(start=0, open=row0[1], high=row0[2], low=row0[3], close=row0[4])
            c1 = Candle(start=0, open=row1[1], high=row1[2], low=row1[3], close=row1[4])
            color0, color1 = candle_color(c0), candle_color(c1)
            entry = {
                "symbol": s["symbol"],
                "candle_1": {"open": c0.open, "high": c0.high, "low": c0.low, "close": c0.close, "color": color0},
                "candle_2": {"open": c1.open, "high": c1.high, "low": c1.low, "close": c1.close, "color": color1},
            }
            if color0 == "green" and color1 == "green":
                gainers.append(entry)
            elif color0 == "red" and color1 == "red":
                losers.append(entry)

        time.sleep(RATE_LIMIT_SLEEP)

    return {
        "date": date_str,
        "window": [time_ist, t1.strftime("%H:%M")],
        "gainers": gainers,
        "losers": losers,
        "errors": errors,
    }
