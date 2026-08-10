from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab")
CYCLES = int(os.getenv("LOAF_SHADOW_CYCLES", "8"))
INTERVAL = float(os.getenv("LOAF_SHADOW_INTERVAL_SECONDS", "15"))
ORDER_SIZE = float(os.getenv("LOAF_ORDER_SIZE", "2"))
MAX_NOTIONAL = float(os.getenv("LOAF_MAX_NOTIONAL_PER_ORDER", "1500"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_MAX_SPREAD_PCT", "1.5"))
QUOTE_OFFSET_BPS = float(os.getenv("LOAF_QUOTE_OFFSET_BPS", "2"))
MAX_INVENTORY = float(os.getenv("LOAF_MAX_INVENTORY", "40"))


def levels(snapshot: dict, name: str) -> list:
    book = snapshot.get("orderBook") or snapshot.get("orderbook") or snapshot
    return (book.get(name, []) or []) if isinstance(book, dict) else []


def px(level) -> float:
    if isinstance(level, dict):
        return float(level.get("price", 0) or 0)
    if isinstance(level, (list, tuple)) and level:
        return float(level[0])
    return 0.0


@dataclass
class ShadowState:
    inventory: float = 0.0
    cash_pnl: float = 0.0
    volume: float = 0.0
    fills: int = 0
    quoted_cycles: int = 0
    previous_bid: float | None = None
    previous_ask: float | None = None


def quote(snapshot: dict, inventory: float) -> dict:
    bids, asks = levels(snapshot, "bids"), levels(snapshot, "asks")
    best_bid = px(bids[0]) if bids else 0.0
    best_ask = px(asks[0]) if asks else 0.0
    out = {"bestBid": best_bid, "bestAsk": best_ask, "decision": "SKIP"}
    if best_bid <= 0 or best_ask <= best_bid:
        out["reason"] = "No valid two-sided book"
        return out
    mid = (best_bid + best_ask) / 2
    spread_pct = (best_ask - best_bid) / mid * 100
    notional = mid * ORDER_SIZE
    if spread_pct > MAX_SPREAD_PCT:
        out.update(mid=mid, spreadPct=spread_pct, reason="Spread limit")
        return out
    if notional > MAX_NOTIONAL:
        out.update(mid=mid, spreadPct=spread_pct, reason="Notional limit")
        return out
    skew = max(-1.0, min(1.0, inventory / MAX_INVENTORY if MAX_INVENTORY else 0.0))
    offset = QUOTE_OFFSET_BPS / 10000
    skew_px = mid * skew * offset
    bid = min(best_ask - mid * 0.0001, best_bid * (1 + offset) - skew_px)
    ask = max(best_bid + mid * 0.0001, best_ask * (1 - offset) - skew_px)
    if bid >= ask:
        out.update(mid=mid, spreadPct=spread_pct, reason="Crossed quote")
        return out
    out.update(decision="WOULD_QUOTE", reason="gates passed", mid=mid, spreadPct=spread_pct,
               proposedBid=bid, proposedAsk=ask, size=ORDER_SIZE)
    return out


def mark_previous_fills(state: ShadowState, best_bid: float, best_ask: float) -> list[dict]:
    fills = []
    # Conservative shadow assumption: a prior bid fills only if the next visible ask trades down to it;
    # a prior ask fills only if the next visible bid trades up to it.
    if state.previous_bid is not None and best_ask > 0 and best_ask <= state.previous_bid and state.inventory + ORDER_SIZE <= MAX_INVENTORY:
        state.inventory += ORDER_SIZE
        state.cash_pnl -= state.previous_bid * ORDER_SIZE
        state.volume += state.previous_bid * ORDER_SIZE
        state.fills += 1
        fills.append({"side": "BUY", "price": state.previous_bid, "size": ORDER_SIZE})
    if state.previous_ask is not None and best_bid > 0 and best_bid >= state.previous_ask and state.inventory - ORDER_SIZE >= -MAX_INVENTORY:
        state.inventory -= ORDER_SIZE
        state.cash_pnl += state.previous_ask * ORDER_SIZE
        state.volume += state.previous_ask * ORDER_SIZE
        state.fills += 1
        fills.append({"side": "SELL", "price": state.previous_ask, "size": ORDER_SIZE})
    return fills


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")
    state = ShadowState()
    rows = []
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        hdr = client.get(f"{BASE}/api/info/{MARKET}/header")
        hdr.raise_for_status()
        property_id = hdr.json().get("propertyId")
        for i in range(CYCLES):
            snap_r = client.get(f"{BASE}/api/trade/{MARKET}")
            snap_r.raise_for_status()
            snap = snap_r.json()
            bids, asks = levels(snap, "bids"), levels(snap, "asks")
            best_bid = px(bids[0]) if bids else 0.0
            best_ask = px(asks[0]) if asks else 0.0
            fills = mark_previous_fills(state, best_bid, best_ask)
            d = quote(snap, state.inventory)
            if d["decision"] == "WOULD_QUOTE":
                state.quoted_cycles += 1
                state.previous_bid = float(d["proposedBid"])
                state.previous_ask = float(d["proposedAsk"])
            else:
                state.previous_bid = None
                state.previous_ask = None
            mid = d.get("mid") or ((best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0)
            marked_pnl = state.cash_pnl + state.inventory * mid
            row = {
                "cycle": i + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "propertyId": property_id,
                "decision": d,
                "shadowFills": fills,
                "inventory": round(state.inventory, 6),
                "shadowVolume": round(state.volume, 2),
                "markedPnl": round(marked_pnl, 2),
            }
            rows.append(row)
            print(json.dumps(row, indent=2))
            if i < CYCLES - 1:
                time.sleep(INTERVAL)

    summary = {
        "mode": "SHADOW_EXECUTION_ONLY",
        "cycles": CYCLES,
        "quotedCycles": state.quoted_cycles,
        "shadowFills": state.fills,
        "shadowVolume": round(state.volume, 2),
        "endingInventory": round(state.inventory, 6),
        "cashComponent": round(state.cash_pnl, 2),
        "note": "Fill model is conservative and simulated; no orders were submitted.",
    }
    print("SHADOW SUMMARY")
    print(json.dumps(summary, indent=2))
    print("SAFE SHADOW COMPLETE: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    main()
