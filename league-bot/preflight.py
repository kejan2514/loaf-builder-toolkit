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


def px(level) -> float:
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


def find_book(node):
    if isinstance(node, dict):
        lower = {str(k).lower(): k for k in node.keys()}
        bid_key = next((lower[k] for k in ("bids", "buyorders", "buy_orders") if k in lower), None)
        ask_key = next((lower[k] for k in ("asks", "sellorders", "sell_orders") if k in lower), None)
        if bid_key is not None or ask_key is not None:
            return node.get(bid_key, []) if bid_key is not None else [], node.get(ask_key, []) if ask_key is not None else []
        for value in node.values():
            found = find_book(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_book(value)
            if found is not None:
                return found
    return None


def best_prices(snapshot: dict) -> tuple[float, float]:
    found = find_book(snapshot)
    if found is None:
        return 0.0, 0.0
    bids, asks = found
    bid_prices = [px(x) for x in bids] if isinstance(bids, list) else []
    ask_prices = [px(x) for x in asks] if isinstance(asks, list) else []
    bid_prices = [p for p in bid_prices if p > 0]
    ask_prices = [p for p in ask_prices if p > 0]
    return (max(bid_prices) if bid_prices else 0.0, min(ask_prices) if ask_prices else 0.0)


def snapshot_shape(node, depth=0, max_depth=3):
    if depth > max_depth:
        return "..."
    if isinstance(node, dict):
        return {str(k): snapshot_shape(v, depth + 1, max_depth) for k, v in list(node.items())[:20]}
    if isinstance(node, list):
        return [snapshot_shape(node[0], depth + 1, max_depth)] if node else []
    return type(node).__name__


def _as_property_id(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def find_property_id(node, market: str | None = None):
    """Resolve propertyId across direct and wrapped Loaf API response shapes."""
    if isinstance(node, dict):
        # Prefer explicit property-id fields at every level.
        normalized = {str(k).lower().replace("_", ""): k for k in node.keys()}
        for candidate in ("propertyid", "propertyidentifier"):
            key = normalized.get(candidate)
            if key is not None:
                parsed = _as_property_id(node.get(key))
                if parsed is not None:
                    return parsed

        # If this looks like a market object and the token matches, accept its numeric id.
        if market:
            names = []
            for key in ("tokenName", "token_name", "token", "symbol", "slug", "name"):
                value = node.get(key)
                if isinstance(value, str):
                    names.append(value.strip().lower())
            if market.strip().lower() in names:
                for key in ("id", "property", "property_id"):
                    if key in node:
                        parsed = _as_property_id(node.get(key))
                        if parsed is not None:
                            return parsed

        # Common wrappers are checked first, then the rest recursively.
        for key in ("data", "result", "market", "property", "header", "payload"):
            if key in node:
                found = find_property_id(node[key], market)
                if found is not None:
                    return found
        for key, value in node.items():
            if key not in ("data", "result", "market", "property", "header", "payload"):
                found = find_property_id(value, market)
                if found is not None:
                    return found

    elif isinstance(node, list):
        for value in node:
            found = find_property_id(value, market)
            if found is not None:
                return found
    return None


def resolve_property_id(client: httpx.Client, header) -> tuple[int | None, str]:
    env_value = os.getenv("LOAF_PROPERTY_ID")
    if env_value:
        parsed = _as_property_id(env_value)
        if parsed is not None:
            return parsed, "env"

    found = find_property_id(header, MARKET)
    if found is not None:
        return found, "info_header"

    # Fallback: Loaf's public trade endpoints can expose the market object even
    # when the Info endpoint changes its response wrapper.
    for path in (f"/api/trade/{MARKET}", "/api/trade"):
        try:
            response = client.get(f"{BASE}{path}")
            response.raise_for_status()
            found = find_property_id(response.json(), MARKET)
            if found is not None:
                return found, path
        except (httpx.HTTPError, ValueError):
            continue

    return None, "unresolved"


def read_book(client: httpx.Client, debug=False) -> tuple[float, float]:
    r = client.get(f"{BASE}/api/trade/{MARKET}")
    r.raise_for_status()
    snap = r.json()
    bid, ask = best_prices(snap)
    if debug:
        print("TRADE SNAPSHOT SHAPE")
        print(json.dumps(snapshot_shape(snap), indent=2))
        print(json.dumps({"parsedBestBid": bid, "parsedBestAsk": ask}))
    return bid, ask


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15, headers=headers) as client:
        h = client.get(f"{BASE}/api/info/{MARKET}/header")
        h.raise_for_status()
        header = h.json()
        property_id, property_id_source = resolve_property_id(client, header)
        if property_id is None:
            print(json.dumps({
                "status": "NOT_READY",
                "reason": "propertyId_unresolved",
                "market": MARKET,
                "apiBase": BASE,
                "headerShape": snapshot_shape(header),
                "nextAction": "Set LOAF_PROPERTY_ID explicitly or inspect the current Loaf market metadata schema",
            }, indent=2))
            sys.exit(1)
        print(json.dumps({
            "market": MARKET,
            "propertyId": property_id,
            "propertyIdSource": property_id_source,
            "apiBase": BASE,
        }))

        mids: list[float] = []
        spreads: list[float] = []
        valid = 0
        print("=== CALIBRATION PHASE ===")
        for i in range(CAL_CYCLES):
            bid, ask = read_book(client, debug=(i == 0))
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
            print(json.dumps({
                "status": "NOT_READY",
                "reason": "REST snapshot still has no safe two-sided quotes",
                "nextAction": f"Use the official Loaf WebSocket orderbook feed (orderbook:{property_id})"
            }, indent=2))
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
            "propertyIdSource": property_id_source,
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
            "note": "Preflight never requests a nonce or places/cancels orders.",
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
