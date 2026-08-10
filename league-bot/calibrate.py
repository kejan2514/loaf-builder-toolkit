from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab")
CYCLES = int(os.getenv("LOAF_CALIBRATION_CYCLES", "12"))
INTERVAL = float(os.getenv("LOAF_CALIBRATION_INTERVAL_SECONDS", "10"))
BASE_SIZE = float(os.getenv("LOAF_ORDER_SIZE", "2"))
MAX_NOTIONAL = float(os.getenv("LOAF_MAX_NOTIONAL_PER_ORDER", "1500"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_MAX_SPREAD_PCT", "1.5"))


def levels(snapshot: dict, name: str) -> list:
    book = snapshot.get("orderBook") or snapshot.get("orderbook") or snapshot
    return (book.get(name, []) or []) if isinstance(book, dict) else []


def px(level) -> float:
    if isinstance(level, dict):
        return float(level.get("price", 0) or 0)
    if isinstance(level, (list, tuple)) and level:
        return float(level[0])
    return 0.0


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    mids: list[float] = []
    spreads: list[float] = []
    valid = 0
    active_orders_seen = 0

    with httpx.Client(timeout=15, headers=headers) as client:
        header = client.get(f"{BASE}/api/info/{MARKET}/header")
        header.raise_for_status()
        property_id = header.json().get("propertyId")

        for i in range(CYCLES):
            snap_r = client.get(f"{BASE}/api/trade/{MARKET}")
            snap_r.raise_for_status()
            snap = snap_r.json()
            orders_r = client.get(f"{BASE}/api/history/orders/active")
            orders_r.raise_for_status()
            raw = orders_r.json()
            orders = raw if isinstance(raw, list) else raw.get("orders", []) if isinstance(raw, dict) else []
            active_orders_seen = max(active_orders_seen, len(orders))

            bids, asks = levels(snap, "bids"), levels(snap, "asks")
            best_bid = px(bids[0]) if bids else 0.0
            best_ask = px(asks[0]) if asks else 0.0
            row = {"cycle": i + 1, "bestBid": best_bid, "bestAsk": best_ask}

            if best_bid > 0 and best_ask > best_bid:
                mid = (best_bid + best_ask) / 2
                spread = (best_ask - best_bid) / mid * 100
                row.update(mid=mid, spreadPct=spread)
                if spread <= MAX_SPREAD_PCT:
                    valid += 1
                    mids.append(mid)
                    spreads.append(spread)
            print(json.dumps(row))
            if i < CYCLES - 1:
                time.sleep(INTERVAL)

    if not mids:
        report = {
            "mode": "CALIBRATION_ONLY",
            "market": MARKET,
            "propertyId": property_id,
            "status": "NO_SAFE_QUOTES",
            "recommendation": "Keep live trading disabled and collect more data.",
        }
        print("CALIBRATION REPORT")
        print(json.dumps(report, indent=2))
        return

    avg_mid = statistics.mean(mids)
    avg_spread = statistics.mean(spreads)
    mid_range_pct = ((max(mids) - min(mids)) / avg_mid * 100) if avg_mid else 0
    quote_ready_rate = valid / CYCLES * 100

    # Conservative adaptive sizing: only increase when the book is consistently safe.
    size = BASE_SIZE
    if quote_ready_rate >= 90 and mid_range_pct < 0.5:
        size = min(BASE_SIZE * 2.0, MAX_NOTIONAL / avg_mid)
    elif quote_ready_rate >= 75 and mid_range_pct < 1.0:
        size = min(BASE_SIZE * 1.5, MAX_NOTIONAL / avg_mid)

    # Keep quotes passive. Tighter offset when spreads are narrow, wider when noisy.
    if avg_spread < 0.20:
        offset_bps = 1
    elif avg_spread < 0.60:
        offset_bps = 2
    else:
        offset_bps = 3

    report = {
        "mode": "CALIBRATION_ONLY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market": MARKET,
        "propertyId": property_id,
        "cycles": CYCLES,
        "quoteReadyRatePct": round(quote_ready_rate, 2),
        "avgMid": round(avg_mid, 8),
        "avgSpreadPct": round(avg_spread, 6),
        "midRangePct": round(mid_range_pct, 6),
        "maxActiveOrdersObserved": active_orders_seen,
        "recommendedOrderSize": round(max(0.1, size), 6),
        "recommendedQuoteOffsetBps": offset_bps,
        "recommendedMaxNotional": MAX_NOTIONAL,
        "liveTradingRecommended": False,
        "note": "Calibration only. Validate shadow fills and platform rules before enabling live trading.",
    }
    print("CALIBRATION REPORT")
    print(json.dumps(report, indent=2))
    print("CALIBRATION COMPLETE: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"HTTP ERROR {exc.response.status_code}")
        sys.exit(1)
