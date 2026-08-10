from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab").lower()
START_UTC = datetime(2026, 8, 13, 2, 0, 0, tzinfo=timezone.utc)


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


def best_book(trade: dict) -> tuple[float, float, int, int]:
    book = trade.get("orderBook") if isinstance(trade, dict) else None
    if not isinstance(book, dict):
        return 0.0, 0.0, 0, 0
    bids_raw = book.get("bids") or []
    asks_raw = book.get("asks") or []
    bids = [level_price(x) for x in bids_raw]
    asks = [level_price(x) for x in asks_raw]
    bids = [x for x in bids if x > 0]
    asks = [x for x in asks if x > 0]
    return (max(bids) if bids else 0.0, min(asks) if asks else 0.0, len(bids_raw), len(asks_raw))


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    now = datetime.now(timezone.utc)
    seconds_to_start = int((START_UTC - now).total_seconds())

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

        bid, ask, bid_levels, ask_levels = best_book(trade)
        liquidity = trade.get("liquidity") if isinstance(trade.get("liquidity"), dict) else {}
        competition_active = bool(trade.get("competitionModeActive", False))
        two_sided = bid > 0 and ask > bid
        after_start = now >= START_UTC
        liquidity_healthy = bool(liquidity.get("healthy", False)) or str(liquidity.get("status", "")).lower() in {"active", "healthy"}

        ready = after_start and two_sided and property_id is not None

        payload = {
            "status": "READY_FOR_GUARDED_PILOT" if ready else "WAITING_FOR_COMPETITION_MARKET",
            "market": MARKET,
            "propertyId": property_id,
            "officialStartUtc": START_UTC.isoformat(),
            "checkedAtUtc": now.isoformat(),
            "secondsToStart": seconds_to_start,
            "afterOfficialStart": after_start,
            "competitionModeActive": competition_active,
            "competitionFlagRole": "informational_only",
            "liquidity": liquidity,
            "liquidityHealthy": liquidity_healthy,
            "bestBid": bid,
            "bestAsk": ask,
            "bidLevels": bid_levels,
            "askLevels": ask_levels,
            "twoSidedBook": two_sided,
            "nextAction": (
                "Guarded Live Pilot may be run manually with enable_live=true."
                if ready
                else "Do not send orders yet; keep monitoring Terafab until the official start and a valid two-sided book appear."
            ),
            "safety": "read-only readiness check; no nonce requested; no order placed; no order cancelled",
        }
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
