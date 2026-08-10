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
CAL_CYCLES = int(os.getenv("LOAF_PREFLIGHT_CAL_CYCLES", "8"))
SHADOW_CYCLES = int(os.getenv("LOAF_PREFLIGHT_SHADOW_CYCLES", "10"))
INTERVAL = float(os.getenv("LOAF_PREFLIGHT_INTERVAL_SECONDS", "8"))
BASE_SIZE = float(os.getenv("LOAF_ORDER_SIZE", "2"))
MAX_NOTIONAL = float(os.getenv("LOAF_MAX_NOTIONAL_PER_ORDER", "1500"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_MAX_SPREAD_PCT", "1.5"))
MAX_MID_RANGE_PCT = float(os.getenv("LOAF_PREFLIGHT_MAX_MID_RANGE_PCT", "1.25"))
MIN_READY_RATE = float(os.getenv("LOAF_PREFLIGHT_MIN_READY_RATE", "75"))


def levels(snapshot: dict, name: str) -> list:
    book = snapshot.get("orderBook") or snapshot.get("orderbook") or snapshot
    return (book.get(name, []) or []) if isinstance(book, dict) else []


def px(level) -> float:
    if isinstance(level, dict):
        return float(level.get("price", 0) or 0)
    if isinstance(level, (list, tuple)) and level:
        return float(level[0])
    return 0.0


def read_book(client: httpx.Client) -> tuple[float, float]:
    r = client.get(f"{BASE}/api/trade/{MARKET}")
    r.raise_for_status()
    snap = r.json()
    bids, asks = levels(snap, "bids"), levels(snap, "asks")
    return (px(bids[0]) if bids else 0.0, px(asks[0]) if asks else 0.0)


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        h = client.get(f"{BASE}/api/info/{MARKET}/header")
        h.raise_for_status()
        property_id = h.json().get("propertyId")

        mids: list[float] = []
        spreads: list[float] = []
        valid = 0
        print("=== CALIBRATION PHASE ===")
        for i in range(CAL_CYCLES):
            bid, ask = read_book(client)
            row = {"phase": "calibration", "cycle": i + 1, "bestBid": bid, "bestAsk": ask}
            if bid > 0 and ask > bid:
                mid = (bid + ask) / 2
                spread = (ask - bid) / mid * 100
                row.update(mid=mid, spreadPct=spread)
                if spread <= MAX_SPREAD_PCT:
                    valid += 1
                    mids.append(mid)
                    spreads.append(spread)
            print(json.dumps(row))
            if i < CAL_CYCLES - 1:
                time.sleep(INTERVAL)

        if not mids:
            print(json.dumps({"status": "NOT_READY", "reason": "No safe two-sided quotes during calibration"}, indent=2))
            return

        avg_mid = statistics.mean(mids)
        avg_spread = statistics.mean(spreads)
        ready_rate = valid / CAL_CYCLES * 100
        mid_range_pct = (max(mids) - min(mids)) / avg_mid * 100 if avg_mid else 0

        if ready_rate >= 90 and mid_range_pct < 0.5:
            size = min(BASE_SIZE * 2.0, MAX_NOTIONAL / avg_mid)
        elif ready_rate >= 75 and mid_range_pct < 1.0:
            size = min(BASE_SIZE * 1.5, MAX_NOTIONAL / avg_mid)
        else:
            size = min(BASE_SIZE, MAX_NOTIONAL / avg_mid)

        offset_bps = 1 if avg_spread < 0.20 else 2 if avg_spread < 0.60 else 3
        size = max(0.1, size)

        print("=== SHADOW VALIDATION ===")
        would_quote = 0
        projected_notional = 0.0
        previous_quote = None
        simulated_fills = 0

        for i in range(SHADOW_CYCLES):
            bid, ask = read_book(client)
            row = {"phase": "shadow", "cycle": i + 1, "bestBid": bid, "bestAsk": ask}
            if bid > 0 and ask > bid:
                mid = (bid + ask) / 2
                spread = (ask - bid) / mid * 100
                notional = mid * size
                row.update(mid=mid, spreadPct=spread, size=round(size, 6), notional=round(notional, 2))

                if previous_quote:
                    prev_bid, prev_ask = previous_quote
                    buy_fill = ask <= prev_bid
                    sell_fill = bid >= prev_ask
                    simulated_fills += int(buy_fill) + int(sell_fill)
                    row.update(simulatedBuyFill=buy_fill, simulatedSellFill=sell_fill)

                if spread <= MAX_SPREAD_PCT and notional <= MAX_NOTIONAL:
                    offset = offset_bps / 10000
                    q_bid = min(bid * (1 + offset), mid * (1 - 0.0001))
                    q_ask = max(ask * (1 - offset), mid * (1 + 0.0001))
                    if q_bid < q_ask:
                        would_quote += 1
                        projected_notional += notional
                        previous_quote = (q_bid, q_ask)
                        row.update(decision="WOULD_QUOTE", proposedBid=round(q_bid, 8), proposedAsk=round(q_ask, 8))
                    else:
                        row.update(decision="SKIP", reason="Crossed quote")
                else:
                    row.update(decision="SKIP", reason="Risk gate")
            else:
                row.update(decision="SKIP", reason="Invalid book")
            print(json.dumps(row))
            if i < SHADOW_CYCLES - 1:
                time.sleep(INTERVAL)

        shadow_ready_rate = would_quote / SHADOW_CYCLES * 100
        ready = (
            ready_rate >= MIN_READY_RATE
            and shadow_ready_rate >= MIN_READY_RATE
            and mid_range_pct <= MAX_MID_RANGE_PCT
            and size * avg_mid <= MAX_NOTIONAL
        )

        report = {
            "mode": "ADAPTIVE_PREFLIGHT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "market": MARKET,
            "propertyId": property_id,
            "status": "READY_FOR_TINY_LIVE_PILOT" if ready else "NOT_READY",
            "calibrationQuoteReadyRatePct": round(ready_rate, 2),
            "shadowQuoteReadyRatePct": round(shadow_ready_rate, 2),
            "avgMid": round(avg_mid, 8),
            "avgSpreadPct": round(avg_spread, 6),
            "midRangePct": round(mid_range_pct, 6),
            "recommendedOrderSize": round(size, 6),
            "recommendedQuoteOffsetBps": offset_bps,
            "maxNotionalPerOrder": MAX_NOTIONAL,
            "shadowSimulatedFills": simulated_fills,
            "projectedQuotedNotional": round(projected_notional, 2),
            "liveTradingEnabled": False,
            "note": "Preflight never requests a nonce or places/cancels orders. A READY result only supports a small supervised pilot, not unattended trading.",
        }
        print("=== PREFLIGHT REPORT ===")
        print(json.dumps(report, indent=2))
        print("SAFE PREFLIGHT COMPLETE: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"HTTP ERROR {exc.response.status_code}")
        sys.exit(1)
