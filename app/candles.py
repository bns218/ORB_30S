"""Builds rolling 30-second OHLC candles per symbol from LTP ticks and
classifies each symbol as a GAINER / LOSER based on two consecutive
same-colour candles:

  - Two consecutive candles that open low, run up, and close at/near the
    high (green, strong body near the top of its range) -> GAINER.
  - Two consecutive candles that open high, run down, and close at/near the
    low (red, strong body near the bottom of its range) -> LOSER.

Candle boundaries are aligned to wall-clock 30s buckets since market open
(09:15:00 IST), independent of when ticks happen to arrive.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

CANDLE_SECONDS = 30
HISTORY_LEN = 5

# A candle counts as a strong green/red candle if its close sits within this
# fraction of the high (green) or low (red) of its own range.
NEAR_EXTREME_RATIO = 0.35


@dataclass
class Candle:
    start: float
    open: float
    high: float
    low: float
    close: float
    ticks: int = 0

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "ticks": self.ticks,
        }


@dataclass
class SymbolState:
    symbol: str
    tradingsymbol: str
    token: str
    day_open: float | None = None
    ltp: float | None = None
    last_update: float | None = None
    cur: Candle | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LEN))


def _bucket_start(ts: float) -> float:
    return (int(ts) // CANDLE_SECONDS) * CANDLE_SECONDS


def candle_color(c: Candle) -> str:
    """Classify a candle as 'green', 'red', or 'neutral' (weak/doji body)."""
    rng = c.high - c.low
    if c.close > c.open:
        pos = 1.0 if rng <= 0 else (c.close - c.low) / rng
        return "green" if pos >= (1 - NEAR_EXTREME_RATIO) else "neutral"
    if c.close < c.open:
        pos = 1.0 if rng <= 0 else (c.close - c.low) / rng
        return "red" if pos <= NEAR_EXTREME_RATIO else "neutral"
    return "neutral"


class CandleAggregator:
    def __init__(self, symbols: list[dict]):
        self._lock = threading.Lock()
        self._state: dict[str, SymbolState] = {}
        for s in symbols:
            token = s["symboltoken"]
            self._state[token] = SymbolState(
                symbol=s["symbol"],
                tradingsymbol=s["tradingsymbol"],
                token=token,
            )

    def on_tick(self, token: str, ltp: float, ts: float | None = None) -> None:
        ts = ts if ts is not None else time.time()
        bucket = _bucket_start(ts)
        with self._lock:
            st = self._state.get(token)
            if st is None:
                return
            if st.day_open is None:
                st.day_open = ltp
            st.ltp = ltp
            st.last_update = ts

            if st.cur is None:
                st.cur = Candle(start=bucket, open=ltp, high=ltp, low=ltp, close=ltp, ticks=1)
                return

            if bucket == st.cur.start:
                st.cur.high = max(st.cur.high, ltp)
                st.cur.low = min(st.cur.low, ltp)
                st.cur.close = ltp
                st.cur.ticks += 1
            else:
                st.history.append(st.cur)
                st.cur = Candle(start=bucket, open=ltp, high=ltp, low=ltp, close=ltp, ticks=1)

    def snapshot(self) -> list[dict]:
        """Return per-symbol state + GAINER/LOSER/NEUTRAL signal."""
        now = time.time()
        cur_bucket = _bucket_start(now)
        out = []
        with self._lock:
            for st in self._state.values():
                if st.ltp is None:
                    continue

                completed = list(st.history)
                if st.cur is not None and st.cur.start != cur_bucket:
                    completed.append(st.cur)

                signal = "NEUTRAL"
                colors: list[str] = []
                if len(completed) >= 2:
                    last_two = completed[-2:]
                    colors = [candle_color(c) for c in last_two]
                    if colors[0] == "green" and colors[1] == "green":
                        signal = "GAINER"
                    elif colors[0] == "red" and colors[1] == "red":
                        signal = "LOSER"

                pct_change = None
                if st.day_open:
                    pct_change = (st.ltp - st.day_open) / st.day_open * 100

                out.append(
                    {
                        "symbol": st.symbol,
                        "tradingsymbol": st.tradingsymbol,
                        "ltp": st.ltp,
                        "day_open": st.day_open,
                        "pct_change": pct_change,
                        "signal": signal,
                        "last_two_colors": colors,
                        "last_candles": [c.to_dict() for c in completed[-3:]],
                        "last_update": st.last_update,
                    }
                )
        return out
