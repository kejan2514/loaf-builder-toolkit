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

BASE_NOTIONAL = float(os.getenv("LOAF_ENGINE_BASE_NOTIONAL", "200"))
MAX_NOTIONAL = float(os.getenv("LOAF_ENGINE_MAX_NOTIONAL", "500"))
MAX_SPREAD_PCT = float(os.getenv("LOAF_ENGINE_MAX_SPREAD_PCT", "1.5"))
QUOTE_IMPROVEMENT_BPS = float(os.getenv("LOAF_ENGINE_QUOTE_IMPROVEMENT_BPS", "1"))
REST_SECONDS = int(os.getenv("LOAF_ENGINE_REST_SECONDS", "8"))
COOLDOWN_SECONDS = int(os.getenv("LOAF_ENGINE_COOLDOWN_SECONDS", "3"))
SESSION_BUDGET_SECONDS = int(os.getenv("LOAF_ENGINE_SESSION_BUDGET_SECONDS", "210"))
MAX_ERRORS = int(os.getenv("LOAF_ENGINE_MAX_ERRORS", "3"))
MAX_EMPTY_BOOKS = int(os.getenv("LOAF_ENGINE_MAX_EMPTY_BOOKS", "12"))


def log(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":"), default=str), flush=True)


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


def read_market(client: httpx.Client) -> tuple[dict, int | None, float, float, int, int]:
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
    bids = [p for p in (level_price(x) for x in bids_raw) if p > 0]
    asks = [p for p in (level_price(x) for x in asks_raw) if p > 0]
    bid = max(bids) if bids else 0.0
    ask = min(asks) if asks else 0.0
    return trade, int(property_id) if property_id is not None else None, bid, ask, len(bids_raw), len(asks_raw)


def active_orders(client: httpx.Client) -> list[dict]:
    r = client.get(f"{BASE}/api/history/orders/active")
    r.raise_for_status()
    raw = r.json()
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("orders"), list):
        return [x for x in raw["orders"] if isinstance(x, dict)]
    return []


def cancel_order(client: httpx.Client, order_id) -> bool:
    r = client.post(f"{BASE}/api/orders/cancel", json={"orderId": order_id})
    if r.status_code == 404:
        log({"event": "CANCEL_ALREADY_GONE", "orderId": order_id})
        return True
    r.raise_for_status()
    log({"event": "CANCEL", "orderId": order_id, "response": r.json()})
    return True


def cancel_all_active(client: httpx.Client) -> int:
    count = 0
    for order in active_orders(client):
        order_id = order.get("orderId")
        if order_id is None:
            continue
        try:
            if cancel_order(client, order_id):
                count += 1
        except Exception as exc:
            log({"event": "CANCEL_ERROR", "orderId": order_id, "error": str(exc)})
    return count


def adaptive_notional(spread_pct: float, elapsed_ratio: float) -> float:
    # Stay conservative in noisy books; use the configured ceiling only when the book is tight.
    amount = BASE_NOTIONAL
    if spread_pct <= 0.20:
        amount *= 1.75
    elif spread_pct <= 0.50:
        amount *= 1.40
    elif spread_pct <= 0.90:
        amount *= 1.15

    # Gradually use more of the configured risk budget later in the round, never above MAX_NOTIONAL.
    if elapsed_ratio >= 0.75:
        amount *= 1.15
    elif elapsed_ratio >= 0.50:
        amount *= 1.08
    return max(10.0, min(MAX_NOTIONAL, amount))


def passive_price(side: str, bid: float, ask: float) -> float:
    mid = (bid + ask) / 2
    improve = QUOTE_IMPROVEMENT_BPS / 10_000
    if side == "BUY":
        proposed = bid * (1 + improve)
        return min(proposed, mid * (1 - 0.00001), ask * (1 - 0.00001))
    proposed = ask * (1 - improve)
    return max(proposed, mid * (1 + 0.00001), bid * (1 + 0.00001))


def place_passive_order(
    client: httpx.Client,
    property_id: int,
    side: str,
    price: float,
    notional: float,
) -> dict:
    nonce_r = client.post(f"{BASE}/api/orders/nonce")
    if nonce_r.status_code == 403:
        return {"status": "TRADING_GATE_CLOSED", "httpStatus": 403, "body": nonce_r.text[:500]}
    nonce_r.raise_for_status()
    nonce_data = nonce_r.json()
    nonce = nonce_data.get("nonce")
    if not nonce:
        return {"status": "ERROR", "reason": "nonce_missing"}

    quantity = notional / price
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


def initial_side(now: datetime) -> str:
    # Alternate the starting direction across five-minute GitHub sessions so restarts do not always bias BUY.
    bucket = int(now.timestamp() // 300)
    return "BUY" if bucket % 2 == 0 else "SELL"


def main() -> None:
    if not TOKEN:
        raise SystemExit("LOAF_API_KEY missing")

    now = datetime.now(timezone.utc)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with httpx.Client(timeout=15, headers=headers) as client:
        if now < START_UTC:
            log({"status": "WAITING_FOR_START", "now": now.isoformat(), "start": START_UTC.isoformat()})
            return

        if now >= END_UTC:
            cleaned = cancel_all_active(client)
            log({"status": "ROUND_ENDED_CLEAN", "now": now.isoformat(), "end": END_UTC.isoformat(), "ordersCancelled": cleaned})
            return

        # Never inherit stale orders from a previous scheduled runner.
        cleaned = cancel_all_active(client)
        log({"event": "SESSION_START", "market": MARKET, "staleOrdersCancelled": cleaned, "sessionBudgetSeconds": SESSION_BUDGET_SECONDS})

        session_started = time.monotonic()
        side = initial_side(now)
        errors = 0
        empty_books = 0
        cycle = 0
        accepted = 0
        inferred_fills = 0
        stale_cancels = 0
        quoted_notional = 0.0

        while time.monotonic() - session_started < SESSION_BUDGET_SECONDS:
            cycle += 1
            current = datetime.now(timezone.utc)
            if current >= END_UTC:
                cancel_all_active(client)
                log({"status": "ROUND_ENDED_DURING_SESSION", "cycle": cycle})
                return

            try:
                trade, property_id, bid, ask, bid_levels, ask_levels = read_market(client)
                competition_flag = bool(trade.get("competitionModeActive", False)) if isinstance(trade, dict) else False
                liquidity = trade.get("liquidity") if isinstance(trade, dict) and isinstance(trade.get("liquidity"), dict) else {}

                if property_id is None or bid <= 0 or ask <= bid:
                    empty_books += 1
                    log({
                        "cycle": cycle,
                        "status": "SKIP",
                        "reason": "no_safe_two_sided_book",
                        "propertyId": property_id,
                        "bestBid": bid,
                        "bestAsk": ask,
                        "bidLevels": bid_levels,
                        "askLevels": ask_levels,
                        "competitionModeActive": competition_flag,
                        "liquidity": liquidity,
                        "emptyBookStreak": empty_books,
                    })
                    if empty_books >= MAX_EMPTY_BOOKS:
                        cancel_all_active(client)
                        log({"status": "SESSION_PAUSED", "reason": "market_book_unavailable", "emptyBookStreak": empty_books})
                        return
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                empty_books = 0
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * 100
                if spread_pct > MAX_SPREAD_PCT:
                    log({"cycle": cycle, "status": "SKIP", "reason": "spread_too_wide", "spreadPct": round(spread_pct, 6)})
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                # Hard invariant: one account order at a time. Never quote both sides simultaneously.
                existing = active_orders(client)
                if existing:
                    for order in existing:
                        oid = order.get("orderId")
                        if oid is not None:
                            cancel_order(client, oid)
                            stale_cancels += 1
                    time.sleep(0.75)

                elapsed_ratio = max(0.0, min(1.0, (current - START_UTC).total_seconds() / (END_UTC - START_UTC).total_seconds()))
                notional = adaptive_notional(spread_pct, elapsed_ratio)
                order_price = passive_price(side, bid, ask)
                if not (bid <= order_price < ask) and side == "BUY":
                    order_price = bid
                if not (bid < order_price <= ask) and side == "SELL":
                    order_price = ask

                placed = place_passive_order(client, property_id, side, order_price, notional)
                log({
                    "cycle": cycle,
                    "competitionModeActive": competition_flag,
                    "spreadPct": round(spread_pct, 6),
                    "elapsedRoundPct": round(elapsed_ratio * 100, 2),
                    **placed,
                })

                if placed.get("status") == "TRADING_GATE_CLOSED":
                    cancel_all_active(client)
                    log({"status": "SESSION_STOPPED", "reason": "trading_gate_closed"})
                    return

                if placed.get("status") != "ORDER_ACCEPTED":
                    errors += 1
                    if errors >= MAX_ERRORS:
                        cancel_all_active(client)
                        log({"status": "KILL_SWITCH", "reason": "order_errors", "errors": errors})
                        return
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                errors = 0
                accepted += 1
                quoted_notional += float(placed.get("notional", 0) or 0)
                order_id = placed.get("orderId")
                time.sleep(REST_SECONDS)

                still_active = any(str(o.get("orderId")) == str(order_id) for o in active_orders(client))
                if still_active:
                    cancel_order(client, order_id)
                    stale_cancels += 1
                    exit_state = "CANCELLED_STALE"
                    # No evidence of a fill: keep the same direction next cycle.
                else:
                    inferred_fills += 1
                    exit_state = "LEFT_ACTIVE_BOOK"
                    # Likely filled or otherwise completed: reverse direction to reduce inventory drift.
                    side = "SELL" if side == "BUY" else "BUY"

                log({"cycle": cycle, "event": "ORDER_EXIT", "orderId": order_id, "state": exit_state, "nextSide": side})
                time.sleep(COOLDOWN_SECONDS)

            except httpx.HTTPStatusError as exc:
                errors += 1
                log({"cycle": cycle, "status": "HTTP_ERROR", "code": exc.response.status_code, "body": exc.response.text[:500], "errors": errors})
                if errors >= MAX_ERRORS:
                    cancel_all_active(client)
                    log({"status": "KILL_SWITCH", "reason": "http_errors", "errors": errors})
                    return
                time.sleep(COOLDOWN_SECONDS)
            except Exception as exc:
                errors += 1
                log({"cycle": cycle, "status": "ERROR", "error": str(exc), "errors": errors})
                if errors >= MAX_ERRORS:
                    cancel_all_active(client)
                    log({"status": "KILL_SWITCH", "reason": "runtime_errors", "errors": errors})
                    return
                time.sleep(COOLDOWN_SECONDS)

        cleaned = cancel_all_active(client)
        log({
            "status": "ENGINE_SESSION_COMPLETE",
            "market": MARKET,
            "cycles": cycle,
            "ordersAccepted": accepted,
            "ordersLeftActiveBookBeforeCancel": inferred_fills,
            "staleCancels": stale_cancels,
            "quotedNotional": round(quoted_notional, 2),
            "baseNotional": BASE_NOTIONAL,
            "maxNotionalPerOrder": MAX_NOTIONAL,
            "finalCleanupCancelled": cleaned,
            "safety": "one passive order only; no self-crossing; adaptive sizing; stale cleanup; error and empty-book kill switches",
        })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "FATAL", "error": str(exc)}, indent=2), flush=True)
        sys.exit(1)
