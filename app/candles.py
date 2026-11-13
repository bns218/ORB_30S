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

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

CANDLE_SECONDS = 30
HISTORY_LEN = 1000  # a full session is ~750 30s candles (09:15-15:30)

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
    prev_close: float | None = None
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
    def __init__(self, symbols: list[dict], log_dir: Path | None = None):
        self._lock = threading.Lock()
        self._state: dict[str, SymbolState] = {}
        for s in symbols:
            token = s["symboltoken"]
            self._state[token] = SymbolState(
                symbol=s["symbol"],
                tradingsymbol=s["tradingsymbol"],
                token=token,
            )
        self._log_dir = log_dir
        self._log_date: str | None = None
        self._log_fh = None
        if self._log_dir is not None:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._preload_today()

    def _preload_today(self) -> None:
        """Reload today's already-logged candles so a restart doesn't lose them."""
        day_str = datetime.now(tz=IST).strftime("%Y-%m-%d")
        path = self._log_dir / f"{day_str}.jsonl"
        if not path.exists():
            return
        by_symbol = {st.symbol: st for st in self._state.values()}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                st = by_symbol.get(row["symbol"])
                if st is None:
                    continue
                st.history.append(
                    Candle(
                        start=row["start"],
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        ticks=row.get("ticks", 0),
                    )
                )
                if st.day_open is None:
                    st.day_open = row["open"]

    def _log_candle(self, st: SymbolState, candle: Candle) -> None:
        if self._log_dir is None:
            return
        day_str = datetime.fromtimestamp(candle.start, tz=IST).strftime("%Y-%m-%d")
        if day_str != self._log_date:
            if self._log_fh is not None:
                self._log_fh.close()
            self._log_fh = open(self._log_dir / f"{day_str}.jsonl", "a", encoding="utf-8")
            self._log_date = day_str
        line = {
            "symbol": st.symbol,
            "tradingsymbol": st.tradingsymbol,
            "start": candle.start,
            "time_ist": datetime.fromtimestamp(candle.start, tz=IST).strftime("%H:%M:%S"),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "ticks": candle.ticks,
            "color": candle_color(candle),
        }
        self._log_fh.write(json.dumps(line) + "\n")
        self._log_fh.flush()

    def on_tick(
        self, token: str, ltp: float, ts: float | None = None, prev_close: float | None = None
    ) -> None:
        ts = ts if ts is not None else time.time()
        bucket = _bucket_start(ts)
        with self._lock:
            st = self._state.get(token)
            if st is None:
                return
            if prev_close:
                st.prev_close = prev_close
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
                self._log_candle(st, st.cur)
                st.cur = Candle(start=bucket, open=ltp, high=ltp, low=ltp, close=ltp, ticks=1)

    def snapshot(self) -> list[dict]:
        """Return per-symbol state + GAINER/LOSER/NEUTRAL signal."""
        now = time.time()
        cur_bucket = _bucket_start(now)
        session_open = (
            datetime.fromtimestamp(now, tz=IST)
            .replace(hour=9, minute=15, second=0, microsecond=0)
            .timestamp()
        )
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

                # Today's move is vs the previous close (falls back to the first
                # price we saw if the feed hasn't sent one yet).
                base = st.prev_close or st.day_open
                pct_change = None
                if base:
                    pct_change = (st.ltp - base) / base * 100

                # Full strip of today's candles (g/r/n per 30s), only for the
                # symbols the dashboard actually lists, to keep the payload small.
                today_colors = ""
                if signal != "NEUTRAL":
                    today_colors = "".join(
                        candle_color(c)[0] for c in completed if c.start >= session_open
                    )

                # The 30s candle still forming right now (None until this
                # bucket's first tick arrives).
                live = None
                if st.cur is not None and st.cur.start == cur_bucket:
                    live = st.cur.to_dict()

                out.append(
                    {
                        "live": live,
                        "today_colors": today_colors,
                        "symbol": st.symbol,
                        "tradingsymbol": st.tradingsymbol,
                        "ltp": st.ltp,
                        "day_open": st.day_open,
                        "prev_close": st.prev_close,
                        "pct_change": pct_change,
                        "signal": signal,
                        "last_two_colors": colors,
                        "last_candles": [c.to_dict() for c in completed[-3:]],
                        "last_update": st.last_update,
                    }
                )
        return out
