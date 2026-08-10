from __future__ import annotations

import json
import os
import sys
import time

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab").lower()
ENABLE_LIVE = os.getenv("LOAF_ENABLE_LIVE", "false").lower() == "true"
CONFIRM = os.getenv("LOAF_LIVE_CONFIRM", "")
MAX_NOTIONAL = float(os.getenv("LOAF_LIVE_MAX_NOTIONAL", "25"))
PILOT_SECONDS = int(os.getenv("LOAF_LIVE_PILOT_SECONDS", "15"))
SIDE = os.getenv("LOAF_LIVE_SIDE", "BUY").upper()


def price(level) -> float:
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


def best_book(trade: dict) -> tuple[float, float]:
    book = trade.get("orderBook") if isinstance(trade, dict) else None
    if not isinstance(book, dict):
        return 0.0, 0.0
    bids = [price(x) for x in (book.get("bids") or [])]
    asks = [price(x) for x in (book.get("asks") or [])]
    bids = [x for x in bids if x > 0]
    asks = [x for x in asks if x > 0]
    return (max(bids) if bids else 0.0, min(asks) if asks else 0.0)


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    if not ENABLE_LIVE or CONFIRM != "RUN_TINY_LIVE_PILOT":
        print(json.dumps({
            "status": "LIVE_DISABLED",
            "note": "Set workflow input enable_live=true to run the supervised pilot."
        }, indent=2))
        return

    if SIDE not in {"BUY", "SELL"}:
        raise SystemExit("LOAF_LIVE_SIDE must be BUY or SELL")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        header_r = client.get(f"{BASE}/api/info/{MARKET}/header")
        header_r.raise_for_status()
        header = header_r.json()

        trade_r = client.get(f"{BASE}/api/trade/{MARKET}")
        trade_r.raise_for_status()
        trade = trade_r.json()

        property_id = header.get("propertyId")
        if property_id is None and isinstance(trade.get("property"), dict):
            property_id = trade["property"].get("propertyId")
        if property_id is None and isinstance(trade.get("orderBook"), dict):
            property_id = trade["orderBook"].get("propertyId")
        if property_id is None:
            raise SystemExit("Could not resolve propertyId")

        competition_active = bool(trade.get("competitionModeActive", False))
        liquidity = trade.get("liquidity") if isinstance(trade.get("liquidity"), dict) else {}
        bid, ask = best_book(trade)

        print(json.dumps({
            "market": MARKET,
            "propertyId": property_id,
            "competitionModeActive": competition_active,
            "liquidity": liquidity,
            "bestBid": bid,
            "bestAsk": ask,
            "mode": "GUARDED_TINY_LIVE_PILOT"
        }, indent=2))

        if not competition_active:
            print(json.dumps({"status": "SKIP", "reason": "Competition mode is not active"}, indent=2))
            return
        if bid <= 0 or ask <= bid:
            print(json.dumps({"status": "SKIP", "reason": "No safe two-sided book"}, indent=2))
            return

        mid = (bid + ask) / 2
        # One passive order only. Never cross the spread and never place opposing self-orders.
        if SIDE == "BUY":
            order_price = bid
        else:
            order_price = ask

        quantity = MAX_NOTIONAL / order_price
        if quantity <= 0:
            raise SystemExit("Invalid pilot quantity")

        nonce_r = client.post(f"{BASE}/api/orders/nonce")
        nonce_r.raise_for_status()
        nonce_data = nonce_r.json()
        nonce = nonce_data.get("nonce")
        if not nonce:
            raise SystemExit("Nonce missing")

        payload = {
            "propertyId": int(property_id),
            "price": round(order_price, 8),
            "quantity": round(quantity, 8),
            "side": SIDE,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "deadline": 0,
            "nonce": nonce,
        }
        print(json.dumps({
            "pilotOrder": {k: v for k, v in payload.items() if k != "nonce"},
            "maxNotional": MAX_NOTIONAL,
            "mid": mid,
            "safety": "single passive order; no opposing self-order; auto-cancel after pilot window"
        }, indent=2))

        placed_r = client.post(f"{BASE}/api/orders/", json=payload)
        placed_r.raise_for_status()
        placed = placed_r.json()
        if not placed.get("success"):
            print(json.dumps({"status": "ORDER_REJECTED", "response": placed}, indent=2))
            return

        order_id = placed.get("orderId")
        print(json.dumps({"status": "PILOT_ORDER_ACCEPTED", "orderId": order_id}, indent=2))
        if not order_id:
            return

        time.sleep(PILOT_SECONDS)

        active_r = client.get(f"{BASE}/api/history/orders/active")
        active_r.raise_for_status()
        active_raw = active_r.json()
        active = active_raw if isinstance(active_raw, list) else active_raw.get("orders", []) if isinstance(active_raw, dict) else []
        still_active = any(str(o.get("orderId")) == str(order_id) for o in active if isinstance(o, dict))

        if still_active:
            cancel_r = client.post(f"{BASE}/api/orders/cancel", json={"orderId": order_id})
            cancel_r.raise_for_status()
            print(json.dumps({"status": "PILOT_CANCELLED", "orderId": order_id, "cancelResponse": cancel_r.json()}, indent=2))
        else:
            print(json.dumps({
                "status": "PILOT_NO_LONGER_ACTIVE",
                "orderId": order_id,
                "note": "Order may have filled or otherwise left the active book; inspect account history before any next pilot."
            }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:1000]
        print(f"HTTP ERROR {exc.response.status_code}: {body}")
        sys.exit(1)
