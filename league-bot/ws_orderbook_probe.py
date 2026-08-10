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
TIMEOUT = float(os.getenv("LOAF_WS_PROBE_TIMEOUT", "20"))


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


def level_price(level) -> float:
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


def best_prices(book: dict) -> tuple[float, float]:
    bids = book.get("bids") or [] if isinstance(book, dict) else []
    asks = book.get("asks") or [] if isinstance(book, dict) else []
    bp = [level_price(x) for x in bids]
    ap = [level_price(x) for x in asks]
    bp = [x for x in bp if x > 0]
    ap = [x for x in ap if x > 0]
    return (max(bp) if bp else 0.0, min(ap) if ap else 0.0)


def market_diag(trade: dict) -> dict:
    order_book = trade.get("orderBook") if isinstance(trade, dict) else {}
    if not isinstance(order_book, dict):
        order_book = {}
    bid, ask = best_prices(order_book)
    liquidity = trade.get("liquidity") if isinstance(trade, dict) else None
    return {
        "competitionModeActive": trade.get("competitionModeActive") if isinstance(trade, dict) else None,
        "marketOpenTime": trade.get("marketOpenTime") if isinstance(trade, dict) else None,
        "marketCloseTime": trade.get("marketCloseTime") if isinstance(trade, dict) else None,
        "marketTimezone": trade.get("marketTimezone") if isinstance(trade, dict) else None,
        "restBidLevels": len(order_book.get("bids") or []),
        "restAskLevels": len(order_book.get("asks") or []),
        "restBestBid": bid,
        "restBestAsk": ask,
        "liquidity": liquidity,
    }


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
        "mode": "READ_ONLY_FEED_DIAGNOSTIC",
        "initialMarket": market_diag(trade),
    }, indent=2))

    ws_url = resolve_ws_url()
    channels = [f"orderbook:{MARKET}", f"markprice:{MARKET}", f"trades:{MARKET}"]
    print(json.dumps({"wsUrl": ws_url, "channels": channels}))

    confirmed = False
    seen_types: set[str] = set()
    orderbook_msg = None

    async with websockets.connect(ws_url, ping_interval=20, close_timeout=3) as ws:
        frame = {"type": "subscribe", "channels": channels}
        print("SUBSCRIBE", json.dumps(frame))
        await ws.send(json.dumps(frame))

        deadline = asyncio.get_running_loop().time() + TIMEOUT
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                continue
            text = raw if isinstance(raw, str) else str(raw)
            print("WS_MESSAGE", text[:1000])
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            msg_type = str(msg.get("type") or "")
            if msg_type:
                seen_types.add(msg_type)
            if msg_type == "subscription_confirmed":
                confirmed = True
            if msg_type == "orderbook_update":
                orderbook_msg = msg
                break

    if orderbook_msg:
        bid, ask = best_prices(orderbook_msg)
        print(json.dumps({
            "status": "WEBSOCKET_ORDERBOOK_OK",
            "tokenName": MARKET,
            "propertyId": property_id,
            "bestBid": bid,
            "bestAsk": ask,
            "bidLevels": len(orderbook_msg.get("bids") or []),
            "askLevels": len(orderbook_msg.get("asks") or []),
            "seenMessageTypes": sorted(seen_types),
        }, indent=2))
        print("SAFE WS PROBE COMPLETE: no nonce requested, no order placed, no order cancelled.")
        return

    with httpx.Client(timeout=15, headers=headers) as client:
        latest_r = client.get(f"{BASE}/api/trade/{MARKET}")
        latest_r.raise_for_status()
        latest = latest_r.json()

    diag = market_diag(latest)
    empty_book = diag["restBidLevels"] == 0 and diag["restAskLevels"] == 0

    if confirmed and empty_book:
        status = "WEBSOCKET_SUBSCRIPTION_OK_MARKET_IDLE"
        note = "Subscription was confirmed. No orderbook event arrived because the current REST snapshot is also empty; wait for market/book activity rather than treating this as a WebSocket failure."
    elif confirmed:
        status = "WEBSOCKET_SUBSCRIPTION_OK_NO_EVENT"
        note = "Subscription was confirmed and the REST book is available, but no incremental orderbook event occurred during the probe window. Use the REST snapshot as the initial state and WebSocket updates incrementally."
    else:
        status = "WEBSOCKET_SUBSCRIPTION_NOT_CONFIRMED"
        note = "The server did not confirm the public channel subscription during the probe window."

    print(json.dumps({
        "status": status,
        "tokenName": MARKET,
        "propertyId": property_id,
        "subscriptionConfirmed": confirmed,
        "seenMessageTypes": sorted(seen_types),
        "latestMarket": diag,
        "note": note,
    }, indent=2))
    print("SAFE WS DIAGNOSTIC COMPLETE: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    asyncio.run(probe())
