from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab").lower()


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
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    out = {
        "mode": "READ_ONLY_SMOKE_TEST",
        "market": MARKET,
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "writesAttempted": False,
    }

    with httpx.Client(timeout=15, headers=headers) as client:
        h = client.get(f"{BASE}/api/info/{MARKET}/header")
        h.raise_for_status()
        header = h.json()

        t = client.get(f"{BASE}/api/trade/{MARKET}")
        t.raise_for_status()
        trade = t.json()

        orders = client.get(f"{BASE}/api/history/orders/active")
        orders.raise_for_status()
        active_raw = orders.json()

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

        if isinstance(active_raw, list):
            active_count = len(active_raw)
        elif isinstance(active_raw, dict) and isinstance(active_raw.get("orders"), list):
            active_count = len(active_raw["orders"])
        else:
            active_count = 0

        out.update({
            "apiAuthenticated": True,
            "propertyId": property_id,
            "competitionModeActive": bool(trade.get("competitionModeActive", False)) if isinstance(trade, dict) else False,
            "bestBid": best_bid,
            "bestAsk": best_ask,
            "bidLevels": len(bids_raw),
            "askLevels": len(asks_raw),
            "twoSidedBook": bool(best_bid > 0 and best_ask > best_bid),
            "activeOrders": active_count,
            "status": "SMOKE_TEST_OK",
        })

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
