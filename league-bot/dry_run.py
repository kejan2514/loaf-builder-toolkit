from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab")
ORDER_SIZE = float(os.getenv("LOAF_ORDER_SIZE", "2"))
MAX_NOTIONAL = float(os.getenv("LOAF_MAX_NOTIONAL_PER_ORDER", "1500"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_MAX_SPREAD_PCT", "1.5"))
QUOTE_OFFSET_BPS = float(os.getenv("LOAF_QUOTE_OFFSET_BPS", "2"))


def levels(snapshot: dict, name: str) -> list:
    book = snapshot.get("orderBook") or snapshot.get("orderbook") or snapshot
    if not isinstance(book, dict):
        return []
    return book.get(name, []) or []


def price(level) -> float:
    if isinstance(level, dict):
        return float(level.get("price", 0))
    if isinstance(level, (list, tuple)) and level:
        return float(level[0])
    return 0.0


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        header_r = client.get(f"{BASE}/api/info/{MARKET}/header")
        header_r.raise_for_status()
        header = header_r.json()

        snap_r = client.get(f"{BASE}/api/trade/{MARKET}")
        snap_r.raise_for_status()
        snap = snap_r.json()

        orders_r = client.get(f"{BASE}/api/history/orders/active")
        orders_r.raise_for_status()
        raw_orders = orders_r.json()
        orders = raw_orders if isinstance(raw_orders, list) else raw_orders.get("orders", []) if isinstance(raw_orders, dict) else []

    bids, asks = levels(snap, "bids"), levels(snap, "asks")
    best_bid = price(bids[0]) if bids else 0.0
    best_ask = price(asks[0]) if asks else 0.0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "DRY_RUN_ONLY",
        "market": MARKET,
        "propertyId": header.get("propertyId"),
        "activeOrders": len(orders),
        "bestBid": best_bid,
        "bestAsk": best_ask,
        "decision": "SKIP",
        "reason": "No valid two-sided book",
    }

    if best_bid > 0 and best_ask > best_bid:
        mid = (best_bid + best_ask) / 2
        spread_pct = (best_ask - best_bid) / mid * 100
        offset = QUOTE_OFFSET_BPS / 10000
        bid = min(best_bid * (1 + offset), mid * (1 - 0.0001))
        ask = max(best_ask * (1 - offset), mid * (1 + 0.0001))
        notional = mid * ORDER_SIZE

        if spread_pct > MAX_SPREAD_PCT:
            report.update(reason=f"Spread {spread_pct:.4f}% exceeds limit {MAX_SPREAD_PCT}%")
        elif notional > MAX_NOTIONAL:
            report.update(reason=f"Order notional {notional:.2f} exceeds limit {MAX_NOTIONAL:.2f}")
        else:
            report.update(
                decision="WOULD_QUOTE",
                reason="Market and risk gates passed",
                mid=round(mid, 8),
                spreadPct=round(spread_pct, 6),
                proposedBid=round(bid, 8),
                proposedAsk=round(ask, 8),
                size=ORDER_SIZE,
                estimatedNotional=round(notional, 2),
            )

    print(json.dumps(report, indent=2))
    print("DRY RUN COMPLETE: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"HTTP ERROR {exc.response.status_code}")
        sys.exit(1)
