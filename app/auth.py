"""SmartAPI login for the standalone dashboard (separate session from the MCP server)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import pyotp
from dotenv import load_dotenv
from SmartApi import SmartConnect

load_dotenv()


@dataclass
class Session:
    connect: SmartConnect
    jwt_token: str
    feed_token: str
    client_code: str
    api_key: str


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def login() -> Session:
    api_key = _require_env("SMARTAPI_API_KEY")
    client_code = _require_env("SMARTAPI_CLIENT_CODE")
    password = _require_env("SMARTAPI_PASSWORD")
    totp_secret = _require_env("SMARTAPI_TOTP_SECRET")

    otp = pyotp.TOTP(totp_secret).now()
    connect = SmartConnect(api_key=api_key)
    session = connect.generateSession(client_code, password, otp)
    if not session.get("status"):
        raise RuntimeError(f"Login failed: {session.get('message')}")

    data = session["data"]
    feed_token = connect.getfeedToken()

    return Session(
        connect=connect,
        jwt_token=data["jwtToken"],
        feed_token=feed_token,
        client_code=client_code,
        api_key=api_key,
    )
