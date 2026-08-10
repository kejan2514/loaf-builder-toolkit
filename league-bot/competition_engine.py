from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab").lower()
START_UTC = datetime(2026, 8, 13, 2, 0, 0, tzinfo=timezone.utc)
END_UTC = datetime(2026, 8, 18, 2, 0, 0, tzinfo=timezone.utc)
MAX_NOTIONAL = float(os.getenv("LOAF_ENGINE_MAX_NOTIONAL", "250"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_ENGINE_MAX_SPREAD_PCT", "2.0"))
CYCLES = int(os.getenv("LOAF_ENGINE_CYCLES", "15"))
REST_SECONDS = int(os.getenv("LOAF_ENGINE_REST_SECONDS", "10"))
COOLDOWN_SECONDS = int(os.getenv("LOAF_ENGINE_COOLDOWN_SECONDS", "6"))
MAX_ERRORS = int(os.getenv("LOAF_ENGINE_MAX_ERRORS", "3"))
START_SIDE = os.getenv("LOAF_ENGINE_START_SIDE", "BUY").upper()


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


def read_market(client: httpx.Client) -> tuple[dict, dict, int | None, float, float]:
    h = client.get(f"{BASE}/api/info/{MARKET}/header")
    h.raise_for_status()
    header = h.json()

    t = client.get(f"{BASE}/api/trade/{MARKET}")
    t.raise_for_status()
    trade = t.json()

    property_id = header.get("propertyId") if isinstance(header, dict) else None
    if property_id is None and isinstance(trade, dict) and isinstance(trade.get("property"), dict):
        property_id = trade["property"].get("propertyId")
    if property_id is None and isinstance(trade, dict) and isinstance(trade.get("orderBook"), dict):
        property_id = trade["orderBook"].get("propertyId")

    book = trade.get("orderBook") if isinstance(trade, dict) else None
    bids_raw = (book.get("bids") or []) if isinstance(book, dict) else []
    asks_raw = (book.get("asks") or []) if isinstance(book, dict) else []
    bids = [level_price(x) for x in bids_raw]
    asks = [level_price(x) for x in asks_raw]
    bids = [x for x in bids if x > 0]
    asks = [x for x in asks if x > 0]
    bid = max(bids) if bids else 0.0
    ask = min(asks) if asks else 0.0
    return header, trade, int(property_id) if property_id is not None else None, bid, ask


def active_orders(client: httpx.Client) -> list[dict]:
    r = client.get(f"{BASE}/api/history/orders/active")
    r.raise_for_status()
    raw = r.json()
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("orders"), list):
        return [x for x in raw["orders"] if isinstance(x, dict)]
    return []


def cancel_order(client: httpx.Client, order_id) -> None:
    r = client.post(f"{BASE}/api/orders/cancel", json={"orderId": order_id})
    r.raise_for_status()
    print(json.dumps({"event": "CANCEL", "orderId": order_id, "response": r.json()}))


def cancel_all_active(client: httpx.Client) -> None:
    for order in active_orders(client):
        order_id = order.get("orderId")
        if order_id is not None:
            try:
                cancel_order(client, order_id)
            except Exception as exc:
                print(json.dumps({"event": "CANCEL_ERROR", "orderId": order_id, "error": str(exc)}))


def place_passive_order(client: httpx.Client, property_id: int, side: str, price: float) -> dict:
    nonce_r = client.post(f"{BASE}/api/orders/nonce")
    if nonce_r.status_code == 403:
        return {"status": "TRADING_GATE_CLOSED", "httpStatus": 403, "body": nonce_r.text[:500]}
    nonce_r.raise_for_status()
    nonce_data = nonce_r.json()
    nonce = nonce_data.get("nonce")
    if not nonce:
        return {"status": "ERROR", "reason": "nonce_missing"}

    quantity = MAX_NOTIONAL / price
    payload = {
        "propertyId": int(property_id),
        "price": round(price, 8),
        "quantity": round(quantity, 8),
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "deadline": 0,
        "nonce": nonce,
    }
    r = client.post(f"{BASE}/api/orders/", json=payload)
    if r.status_code == 403:
        return {"status": "TRADING_GATE_CLOSED", "httpStatus": 403, "body": r.text[:500]}
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        return {"status": "ORDER_REJECTED", "response": data}
    return {
        "status": "ORDER_ACCEPTED",
        "orderId": data.get("orderId"),
        "side": side,
        "price": round(price, 8),
        "quantity": round(quantity, 8),
        "notional": round(price * quantity, 2),
    }


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")
    if START_SIDE not in {"BUY", "SELL"}:
        raise SystemExit("LOAF_ENGINE_START_SIDE must be BUY or SELL")

    now = datetime.now(timezone.utc)
    if now < START_UTC:
        print(json.dumps({"status": "WAITING_FOR_START", "now": now.isoformat(), "start": START_UTC.isoformat()}, indent=2))
        return
    if now >= END_UTC:
        print(json.dumps({"status": "ROUND_ENDED", "now": now.isoformat(), "end": END_UTC.isoformat()}, indent=2))
        return

    headers = {"Authorization": f"Bearer {TOKEN}"}
    errors = 0
    side = START_SIDE
    placed_count = 0
    completed_count = 0
    quoted_notional = 0.0

    with httpx.Client(timeout=15, headers=headers) as client:
        # Never begin a cycle with stale account orders from a previous run.
        cancel_all_active(client)

        for cycle in range(1, CYCLES + 1):
            try:
                _, trade, property_id, bid, ask = read_market(client)
                competition_flag = bool(trade.get("competitionModeActive", False)) if isinstance(trade, dict) else False
                liquidity = trade.get("liquidity") if isinstance(trade, dict) and isinstance(trade.get("liquidity"), dict) else {}

                if property_id is None or bid <= 0 or ask <= bid:
                    print(json.dumps({
                        "cycle": cycle,
                        "status": "SKIP",
                        "reason": "no_safe_two_sided_book",
                        "propertyId": property_id,
                        "bestBid": bid,
                        "bestAsk": ask,
                        "competitionModeActive": competition_flag,
                        "liquidity": liquidity,
                    }))
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * 100
                if spread_pct > MAX_SPREAD_PCT:
                    print(json.dumps({"cycle": cycle, "status": "SKIP", "reason": "spread_too_wide", "spreadPct": spread_pct}))
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                # Safety invariant: at most one account order at a time. Cancel anything stale first.
                existing = active_orders(client)
                if existing:
                    for order in existing:
                        if order.get("orderId") is not None:
                            cancel_order(client, order.get("orderId"))
                    time.sleep(1)

                order_price = bid if side == "BUY" else ask
                placed = place_passive_order(client, property_id, side, order_price)
                print(json.dumps({"cycle": cycle, "competitionModeActive": competition_flag, "spreadPct": round(spread_pct, 6), **placed}))

                if placed.get("status") == "TRADING_GATE_CLOSED":
                    print(json.dumps({"status": "ENGINE_STOPPED", "reason": "trading_gate_closed"}, indent=2))
                    return
                if placed.get("status") != "ORDER_ACCEPTED":
                    errors += 1
                    if errors >= MAX_ERRORS:
                        print(json.dumps({"status": "KILL_SWITCH", "reason": "max_errors", "errors": errors}, indent=2))
                        cancel_all_active(client)
                        return
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                errors = 0
                placed_count += 1
                quoted_notional += float(placed.get("notional", 0) or 0)
                order_id = placed.get("orderId")
                time.sleep(REST_SECONDS)

                still_active = any(str(o.get("orderId")) == str(order_id) for o in active_orders(client))
                if still_active:
                    cancel_order(client, order_id)
                    exit_state = "CANCELLED_STALE"
                else:
                    completed_count += 1
                    exit_state = "LEFT_ACTIVE_BOOK"

                print(json.dumps({"cycle": cycle, "event": "ORDER_EXIT", "orderId": order_id, "state": exit_state}))

                # Sequential alternation only; never maintain opposing orders simultaneously.
                side = "SELL" if side == "BUY" else "BUY"
                time.sleep(COOLDOWN_SECONDS)

            except httpx.HTTPStatusError as exc:
                errors += 1
                print(json.dumps({"cycle": cycle, "status": "HTTP_ERROR", "code": exc.response.status_code, "body": exc.response.text[:500]}))
                if errors >= MAX_ERRORS:
                    cancel_all_active(client)
                    print(json.dumps({"status": "KILL_SWITCH", "reason": "http_errors", "errors": errors}, indent=2))
                    return
                time.sleep(COOLDOWN_SECONDS)
            except Exception as exc:
                errors += 1
                print(json.dumps({"cycle": cycle, "status": "ERROR", "error": str(exc)}))
                if errors >= MAX_ERRORS:
                    cancel_all_active(client)
                    print(json.dumps({"status": "KILL_SWITCH", "reason": "runtime_errors", "errors": errors}, indent=2))
                    return
                time.sleep(COOLDOWN_SECONDS)

        cancel_all_active(client)
        print(json.dumps({
            "status": "ENGINE_SESSION_COMPLETE",
            "market": MARKET,
            "cycles": CYCLES,
            "ordersAccepted": placed_count,
            "ordersNoLongerActiveBeforeCancel": completed_count,
            "quotedNotional": round(quoted_notional, 2),
            "maxNotionalPerOrder": MAX_NOTIONAL,
            "safety": "single passive order only; no simultaneous opposing orders; stale-order cancellation; error kill-switch",
        }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "FATAL", "error": str(exc)}, indent=2))
        sys.exit(1)
