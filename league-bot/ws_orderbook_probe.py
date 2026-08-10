from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import urlparse

import httpx
import websockets

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab").lower()
WS_URL = os.getenv("LOAF_WS_URL", "")
TIMEOUT = float(os.getenv("LOAF_WS_PROBE_TIMEOUT", "12"))


def resolve_ws_url() -> str:
    if WS_URL:
        return WS_URL
    parsed = urlparse(BASE)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/ws"


def extract_property_id(header: dict, trade: dict) -> int | None:
    candidates = [
        header.get("propertyId") if isinstance(header, dict) else None,
        (header.get("property") or {}).get("propertyId") if isinstance(header, dict) and isinstance(header.get("property"), dict) else None,
        trade.get("propertyId") if isinstance(trade, dict) else None,
        (trade.get("property") or {}).get("propertyId") if isinstance(trade, dict) and isinstance(trade.get("property"), dict) else None,
        (trade.get("orderBook") or {}).get("propertyId") if isinstance(trade, dict) and isinstance(trade.get("orderBook"), dict) else None,
    ]
    for value in candidates:
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def best_prices(message: dict) -> tuple[float, float]:
    bids = message.get("bids") or []
    asks = message.get("asks") or []

    def p(level):
        if isinstance(level, dict):
            try:
                return float(level.get("price", 0) or 0)
            except (TypeError, ValueError):
                return 0.0
        if isinstance(level, (list, tuple)) and level:
            try:
                return float(level[0])
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    bp = [p(x) for x in bids]
    ap = [p(x) for x in asks]
    bp = [x for x in bp if x > 0]
    ap = [x for x in ap if x > 0]
    return (max(bp) if bp else 0.0, min(ap) if ap else 0.0)


async def probe() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        h = client.get(f"{BASE}/api/info/{MARKET}/header")
        h.raise_for_status()
        t = client.get(f"{BASE}/api/trade/{MARKET}")
        t.raise_for_status()
        header, trade = h.json(), t.json()

    property_id = extract_property_id(header, trade)
    print(json.dumps({
        "market": MARKET,
        "resolvedPropertyId": property_id,
        "headerTopKeys": list(header.keys())[:20] if isinstance(header, dict) else [],
        "tradeTopKeys": list(trade.keys())[:20] if isinstance(trade, dict) else [],
    }))

    ws_url = resolve_ws_url()
    # Current Loaf WS channels are keyed by lowercase tokenName, not propertyId.
    channel = f"orderbook:{MARKET}"
    print(json.dumps({"wsUrl": ws_url, "channel": channel, "mode": "READ_ONLY_PROBE"}))

    async with websockets.connect(ws_url, ping_interval=20, close_timeout=3) as ws:
        # The gateway expects channels to be an array of strings.
        frame = {"type": "subscribe", "channels": [channel]}
        print("SUBSCRIBE", json.dumps(frame))
        await ws.send(json.dumps(frame))

        deadline = asyncio.get_running_loop().time() + TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                continue
            print("WS_MESSAGE", raw[:1500] if isinstance(raw, str) else str(raw)[:1500])
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            if isinstance(msg, dict) and msg.get("type") == "orderbook_update":
                bid, ask = best_prices(msg)
                print(json.dumps({
                    "status": "WEBSOCKET_ORDERBOOK_OK",
                    "tokenName": MARKET,
                    "propertyId": msg.get("propertyId", property_id),
                    "bestBid": bid,
                    "bestAsk": ask,
                    "bidLevels": len(msg.get("bids") or []),
                    "askLevels": len(msg.get("asks") or []),
                }, indent=2))
                print("SAFE WS PROBE COMPLETE: no nonce requested, no order placed, no order cancelled.")
                return

            if isinstance(msg, dict) and msg.get("type") == "error":
                print(json.dumps({
                    "status": "WS_SUBSCRIPTION_ERROR",
                    "channel": channel,
                    "serverError": msg,
                }, indent=2))

    print(json.dumps({
        "status": "NO_ORDERBOOK_UPDATE",
        "tokenName": MARKET,
        "propertyId": property_id,
        "channel": channel,
        "note": "Connected and subscribed using tokenName, but no orderbook_update arrived within the probe timeout."
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(probe())
