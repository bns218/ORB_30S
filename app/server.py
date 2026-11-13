from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import login
from app.candles import CandleAggregator
from app.feed import FeedRunner
from app.replay import classify_window

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
SYMBOLS_PATH = ROOT / "data" / "fo_stocks.json"
CANDLE_LOG_DIR = ROOT / "data" / "candle_log"

class NoCacheStaticFiles(StaticFiles):
    """Dashboard assets change while it's being developed; never let the browser reuse stale ones."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app = FastAPI()
app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")

_clients: set[WebSocket] = set()
_aggregator: CandleAggregator | None = None
_feed: FeedRunner | None = None


def _load_symbols() -> list[dict]:
    raw = json.loads(SYMBOLS_PATH.read_text(encoding="utf-8"))
    out = []
    for symbol, info in raw.items():
        out.append(
            {
                "symbol": symbol,
                "tradingsymbol": info["tradingsymbol"],
                "symboltoken": info["symboltoken"],
            }
        )
    return out


@app.on_event("startup")
async def startup() -> None:
    global _aggregator, _feed
    symbols = _load_symbols()
    _aggregator = CandleAggregator(symbols, log_dir=CANDLE_LOG_DIR)

    logger.info("Logging in to SmartAPI...")
    session = await asyncio.to_thread(login)
    logger.info("Logged in as %s", session.client_code)

    _feed = FeedRunner(session, symbols, _aggregator)
    _feed.start()

    asyncio.create_task(_broadcaster())


async def _broadcaster() -> None:
    while True:
        await asyncio.sleep(1.0)
        if not _clients or _aggregator is None:
            continue
        payload = json.dumps(
            {
                "type": "snapshot",
                "server_time": time.time(),
                "connected": bool(_feed and _feed.connected.is_set()),
                "data": _aggregator.snapshot(),
            }
        )
        dead = []
        for ws in _clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/snapshot")
async def snapshot() -> dict:
    if _aggregator is None:
        return {"connected": False, "data": []}
    return {"connected": bool(_feed and _feed.connected.is_set()), "data": _aggregator.snapshot()}


@app.get("/api/window")
async def window(time: str, date: str | None = None) -> dict:
    """GAINER/LOSER classification for a specific logged 30s window.

    time: 'HH:MM' or 'HH:MM:SS' in IST, e.g. '09:15:00' -> classifies using
        the candle starting at that time plus the one immediately after it.
    date: 'YYYY-MM-DD' IST, defaults to today.
    """
    from datetime import datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    date = date or datetime.now(tz=ist).strftime("%Y-%m-%d")
    return classify_window(CANDLE_LOG_DIR, date, time)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
