from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab").lower()
SIM_NOTIONAL = float(os.getenv("LOAF_SIM_NOTIONAL", "250"))
SIDE = os.getenv("LOAF_SIM_SIDE", "BUY").upper()
USE_SYNTHETIC_IF_EMPTY = os.getenv("LOAF_SIM_SYNTHETIC_IF_EMPTY", "true").lower() == "true"


def level_price(level) -> float:
    if isinstance(level, dict):
        for key in ("price", "px", "p"):
            if key in level:
                try:
                    return float(level.get(key) or 0)
                except (TypeError, ValueError):
                    return 0.0
    if isinstance(level, (list, tuple)) and level:
        try:
            return float(level[0])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def main() -> None:
    if SIDE not in {"BUY", "SELL"}:
        raise SystemExit("LOAF_SIM_SIDE must be BUY or SELL")
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        header_r = client.get(f"{BASE}/api/info/{MARKET}/header")
        header_r.raise_for_status()
        header = header_r.json()

        trade_r = client.get(f"{BASE}/api/trade/{MARKET}")
        trade_r.raise_for_status()
        trade = trade_r.json()

        property_id = header.get("propertyId") if isinstance(header, dict) else None
        if property_id is None and isinstance(trade, dict) and isinstance(trade.get("property"), dict):
            property_id = trade["property"].get("propertyId")

        book = trade.get("orderBook") if isinstance(trade, dict) else None
        bids_raw = (book.get("bids") or []) if isinstance(book, dict) else []
        asks_raw = (book.get("asks") or []) if isinstance(book, dict) else []
        bids = [p for p in (level_price(x) for x in bids_raw) if p > 0]
        asks = [p for p in (level_price(x) for x in asks_raw) if p > 0]
        best_bid = max(bids) if bids else 0.0
        best_ask = min(asks) if asks else 0.0

        source = "LIVE_BOOK"
        if best_bid <= 0 or best_ask <= best_bid:
            if not USE_SYNTHETIC_IF_EMPTY:
                print(json.dumps({
                    "status": "WAITING_FOR_BOOK",
                    "mode": "SIMULATED_ORDER_TEST",
                    "market": MARKET,
                    "propertyId": property_id,
                    "bestBid": best_bid,
                    "bestAsk": best_ask,
                    "writesAttempted": False,
                }, indent=2))
                return
            best_bid, best_ask = 99.90, 100.10
            source = "SYNTHETIC_BOOK_FIXTURE"

        mid = (best_bid + best_ask) / 2
        price = best_bid if SIDE == "BUY" else best_ask
        quantity = SIM_NOTIONAL / price
        payload = {
            "propertyId": int(property_id) if property_id is not None else 12,
            "price": round(price, 8),
            "quantity": round(quantity, 8),
            "side": SIDE,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "deadline": 0,
            "nonce": "<NOT_REQUESTED_IN_SIMULATION>",
        }

        print(json.dumps({
            "status": "SIMULATED_ORDER_READY",
            "mode": "ZERO_WRITE_SIMULATION",
            "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
            "market": MARKET,
            "propertyId": property_id,
            "competitionModeActive": bool(trade.get("competitionModeActive", False)) if isinstance(trade, dict) else False,
            "bookSource": source,
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "mid": round(mid, 8),
            "simulatedNotional": round(SIM_NOTIONAL, 2),
            "candidateOrderPayload": payload,
            "writesAttempted": False,
            "nonceRequested": False,
            "orderSubmitted": False,
            "orderCancelled": False,
            "note": "This test validates the exact candidate order payload shape without calling any write endpoint.",
        }, indent=2))


if __name__ == "__main__":
    main()
