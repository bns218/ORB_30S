"""AngelOne SmartAPI WebSocket2.0 feed -> CandleAggregator, run on a
background thread (the SDK's connect() call is blocking / run_forever).
"""
from __future__ import annotations

import logging
import threading
import time

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from app.auth import Session
from app.candles import CandleAggregator

logger = logging.getLogger("feed")

NSE_CM = 1
QUOTE_MODE = 2
CHUNK = 50  # tokens per subscribe call


class FeedRunner:
    def __init__(self, session: Session, symbols: list[dict], aggregator: CandleAggregator):
        self.session = session
        self.symbols = symbols
        self.aggregator = aggregator
        self.ws: SmartWebSocketV2 | None = None
        self.connected = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.ws = SmartWebSocketV2(
            auth_token=self.session.jwt_token,
            api_key=self.session.api_key,
            client_code=self.session.client_code,
            feed_token=self.session.feed_token,
            max_retry_attempt=50,
            retry_strategy=1,
            retry_delay=2,
            retry_multiplier=2,
            retry_duration=60,
        )
        self.ws.on_open = self._on_open
        self.ws.on_data = self._on_data
        self.ws.on_error = self._on_error
        self.ws.on_close = self._on_close

        self._thread = threading.Thread(target=self.ws.connect, daemon=True, name="smartapi-ws")
        self._thread.start()

    def _on_open(self, wsapp) -> None:
        logger.info("WebSocket connected, subscribing %d symbols", len(self.symbols))
        tokens = [s["symboltoken"] for s in self.symbols]
        for i in range(0, len(tokens), CHUNK):
            chunk = tokens[i : i + CHUNK]
            self.ws.subscribe(
                correlation_id=f"fo30s{i}",
                mode=QUOTE_MODE,
                token_list=[{"exchangeType": NSE_CM, "tokens": chunk}],
            )
            time.sleep(0.2)
        self.connected.set()

    def _on_data(self, wsapp, message: dict) -> None:
        token = message.get("token")
        ltp_paise = message.get("last_traded_price")
        if token is None or ltp_paise is None:
            return
        ts_ms = message.get("exchange_timestamp")
        ts = ts_ms / 1000.0 if ts_ms else time.time()
        prev_close_paise = message.get("closed_price")
        prev_close = prev_close_paise / 100.0 if prev_close_paise else None
        self.aggregator.on_tick(token, ltp_paise / 100.0, ts, prev_close=prev_close)

    def _on_error(self, wsapp, error) -> None:
        logger.error("WebSocket error: %s", error)

    def _on_close(self, wsapp, *args) -> None:
        logger.warning("WebSocket closed")
        self.connected.clear()
