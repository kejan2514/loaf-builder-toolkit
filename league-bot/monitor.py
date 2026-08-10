from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab")
CYCLES = int(os.getenv("LOAF_MONITOR_CYCLES", "6"))
INTERVAL = float(os.getenv("LOAF_MONITOR_INTERVAL_SECONDS", "20"))
ORDER_SIZE = float(os.getenv("LOAF_ORDER_SIZE", "2"))
MAX_NOTIONAL = float(os.getenv("LOAF_MAX_NOTIONAL_PER_ORDER", "1500"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_MAX_SPREAD_PCT", "1.5"))
QUOTE_OFFSET_BPS = float(os.getenv("LOAF_QUOTE_OFFSET_BPS", "2"))


def levels(snapshot: dict, name: str) -> list:
    book = snapshot.get("orderBook") or snapshot.get("orderbook") or snapshot
    return (book.get(name, []) or []) if isinstance(book, dict) else []


def px(level) -> float:
    if isinstance(level, dict):
        return float(level.get("price", 0) or 0)
    if isinstance(level, (list, tuple)) and level:
        return float(level[0])
    return 0.0


def decision(snapshot: dict) -> dict:
    bids, asks = levels(snapshot, "bids"), levels(snapshot, "asks")
    best_bid = px(bids[0]) if bids else 0.0
    best_ask = px(asks[0]) if asks else 0.0
    out = {"bestBid": best_bid, "bestAsk": best_ask, "decision": "SKIP", "reason": "No valid two-sided book"}
    if best_bid <= 0 or best_ask <= best_bid:
        return out
    mid = (best_bid + best_ask) / 2
    spread_pct = (best_ask - best_bid) / mid * 100
    notional = mid * ORDER_SIZE
    out.update(mid=round(mid, 8), spreadPct=round(spread_pct, 6), estimatedNotional=round(notional, 2))
    if spread_pct > MAX_SPREAD_PCT:
        out["reason"] = f"Spread {spread_pct:.4f}% exceeds limit {MAX_SPREAD_PCT}%"
        return out
    if notional > MAX_NOTIONAL:
        out["reason"] = f"Order notional {notional:.2f} exceeds limit {MAX_NOTIONAL:.2f}"
        return out
    offset = QUOTE_OFFSET_BPS / 10000
    bid = min(best_bid * (1 + offset), mid * (1 - 0.0001))
    ask = max(best_ask * (1 - offset), mid * (1 + 0.0001))
    out.update(decision="WOULD_QUOTE", reason="Market and risk gates passed", proposedBid=round(bid, 8), proposedAsk=round(ask, 8), size=ORDER_SIZE)
    return out


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    results = []
    with httpx.Client(timeout=15, headers=headers) as client:
        header = client.get(f"{BASE}/api/info/{MARKET}/header")
        header.raise_for_status()
        property_id = header.json().get("propertyId")
        for i in range(CYCLES):
            snap = client.get(f"{BASE}/api/trade/{MARKET}")
            snap.raise_for_status()
            orders = client.get(f"{BASE}/api/history/orders/active")
            orders.raise_for_status()
            raw = orders.json()
            active = raw if isinstance(raw, list) else raw.get("orders", []) if isinstance(raw, dict) else []
            row = {"cycle": i + 1, "timestamp": datetime.now(timezone.utc).isoformat(), "market": MARKET, "propertyId": property_id, "activeOrders": len(active)}
            row.update(decision(snap.json()))
            results.append(row)
            print(json.dumps(row, indent=2))
            if i < CYCLES - 1:
                time.sleep(INTERVAL)
    quotes = [r for r in results if r["decision"] == "WOULD_QUOTE"]
    summary = {
        "mode": "MULTI_CYCLE_DRY_MONITOR",
        "cycles": len(results),
        "quoteReadyCycles": len(quotes),
        "skipCycles": len(results) - len(quotes),
        "quoteReadyRatePct": round((len(quotes) / len(results) * 100) if results else 0, 2),
        "minMid": min((r.get("mid") for r in results if r.get("mid") is not None), default=None),
        "maxMid": max((r.get("mid") for r in results if r.get("mid") is not None), default=None),
    }
    print("MONITOR SUMMARY")
    print(json.dumps(summary, indent=2))
    print("SAFE MONITOR COMPLETE: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"HTTP ERROR {exc.response.status_code}")
        sys.exit(1)
