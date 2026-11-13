"""Query logged 30s candles for a specific past window on a given day,
e.g. "what were the GAINER/LOSER stocks at the 09:15:00 candle?"

Reads the JSONL candle log written by CandleAggregator (one line per
completed candle per symbol) — see app/candles.py::_log_candle.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
CANDLE_SECONDS = 30


def _epoch_for_ist_time(date_str: str, hhmmss: str) -> int:
    """date_str: 'YYYY-MM-DD', hhmmss: 'HH:MM' or 'HH:MM:SS', both IST."""
    parts = hhmmss.split(":")
    if len(parts) == 2:
        hhmmss = hhmmss + ":00"
    dt = datetime.strptime(f"{date_str} {hhmmss}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    epoch = int(dt.timestamp())
    return (epoch // CANDLE_SECONDS) * CANDLE_SECONDS


def load_day(log_dir: Path, date_str: str) -> dict[str, list[dict]]:
    """symbol -> list of candle dicts, sorted by start time."""
    path = log_dir / f"{date_str}.jsonl"
    by_symbol: dict[str, list[dict]] = {}
    if not path.exists():
        return by_symbol
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            by_symbol.setdefault(row["symbol"], []).append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r["start"])
    return by_symbol


def classify_window(log_dir: Path, date_str: str, time_ist: str) -> dict:
    """Classify every symbol using the candle starting at `time_ist` and the
    one immediately after it (time_ist + 30s), same rule as the live
    dashboard: two greens -> GAINER, two reds -> LOSER.
    """
    t0 = _epoch_for_ist_time(date_str, time_ist)
    t1 = t0 + CANDLE_SECONDS
    by_symbol = load_day(log_dir, date_str)

    gainers = []
    losers = []
    for symbol, rows in by_symbol.items():
        by_start = {r["start"]: r for r in rows}
        c0 = by_start.get(t0)
        c1 = by_start.get(t1)
        if c0 is None or c1 is None:
            continue
        colors = [c0["color"], c1["color"]]
        entry = {
            "symbol": symbol,
            "candle_1": c0,
            "candle_2": c1,
        }
        if colors == ["green", "green"]:
            gainers.append(entry)
        elif colors == ["red", "red"]:
            losers.append(entry)

    return {"date": date_str, "window": [t0, t1], "gainers": gainers, "losers": losers}
