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

# Round 1 is volume-maxxing. 30M+ is the published 5x multiplier tier.
# Aim slightly above it so ordinary downtime does not immediately drop us below pace.
ROUND_VOLUME_TARGET = float(os.getenv("LOAF_ENGINE_ROUND_VOLUME_TARGET", "35000000"))
SESSION_BUDGET_SECONDS = int(os.getenv("LOAF_ENGINE_SESSION_BUDGET_SECONDS", "210"))

# Maker-first: maker fee is 0%; taker is used only to stay on target pace in a tight book.
MAKER_NOTIONAL = float(os.getenv("LOAF_ENGINE_MAKER_NOTIONAL", "3000"))
TAKER_NOTIONAL = float(os.getenv("LOAF_ENGINE_TAKER_NOTIONAL", "1250"))
MAX_TAKER_NOTIONAL = float(os.getenv("LOAF_ENGINE_MAX_TAKER_NOTIONAL", "2000"))
MAX_MAKER_SPREAD_PCT = float(os.getenv("LOAF_ENGINE_MAX_MAKER_SPREAD_PCT", "1.0"))
MAX_TAKER_SPREAD_PCT = float(os.getenv("LOAF_ENGINE_MAX_TAKER_SPREAD_PCT", "0.10"))
QUOTE_IMPROVEMENT_BPS = float(os.getenv("LOAF_ENGINE_QUOTE_IMPROVEMENT_BPS", "1"))
MAKER_REST_SECONDS = int(os.getenv("LOAF_ENGINE_MAKER_REST_SECONDS", "5"))
COOLDOWN_SECONDS = float(os.getenv("LOAF_ENGINE_COOLDOWN_SECONDS", "1.5"))
MAX_ERRORS = int(os.getenv("LOAF_ENGINE_MAX_ERRORS", "3"))
MAX_EMPTY_BOOKS = int(os.getenv("LOAF_ENGINE_MAX_EMPTY_BOOKS", "12"))
DEPTH_FRACTION = float(os.getenv("LOAF_ENGINE_DEPTH_FRACTION", "0.30"))


def log(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":"), default=str), flush=True)


def fnum(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def level_price(level) -> float:
    if isinstance(level, dict):
        for key in ("price", "px", "p"):
            if key in level:
                return fnum(level.get(key))
    if isinstance(level, (list, tuple)) and level:
        return fnum(level[0])
    return 0.0


def level_qty(level) -> float:
    if isinstance(level, dict):
        for key in ("quantity", "qty", "size", "amount", "q"):
            if key in level:
                return fnum(level.get(key))
    if isinstance(level, (list, tuple)) and len(level) > 1:
        return fnum(level[1])
    return 0.0


def read_market(client: httpx.Client) -> tuple[dict, int | None, float, float, float, float, int, int]:
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

    bids = [(level_price(x), level_qty(x)) for x in bids_raw]
    asks = [(level_price(x), level_qty(x)) for x in asks_raw]
    bids = [(p, q) for p, q in bids if p > 0]
    asks = [(p, q) for p, q in asks if p > 0]
    best_bid, bid_qty = max(bids, key=lambda x: x[0]) if bids else (0.0, 0.0)
    best_ask, ask_qty = min(asks, key=lambda x: x[0]) if asks else (0.0, 0.0)

    return (
        trade,
        int(property_id) if property_id is not None else None,
        best_bid,
        best_ask,
        bid_qty,
        ask_qty,
        len(bids_raw),
        len(asks_raw),
    )


def active_orders(client: httpx.Client) -> list[dict]:
    r = client.get(f"{BASE}/api/history/orders/active")
    r.raise_for_status()
    raw = r.json()
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        for key in ("activeOrders", "orders", "data"):
            if isinstance(raw.get(key), list):
                return [x for x in raw[key] if isinstance(x, dict)]
    return []


def cancel_order(client: httpx.Client, order_id) -> bool:
    r = client.post(f"{BASE}/api/orders/cancel", json={"orderId": order_id})
    if r.status_code == 404:
        return True
    r.raise_for_status()
    log({"event": "CANCEL", "orderId": order_id})
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


def fresh_nonce(client: httpx.Client) -> tuple[str | None, dict | None]:
    r = client.post(f"{BASE}/api/orders/nonce")
    if r.status_code == 403:
        return None, {"status": "TRADING_GATE_CLOSED", "httpStatus": 403, "body": r.text[:300]}
    r.raise_for_status()
    data = r.json()
    nonce = data.get("nonce") if isinstance(data, dict) else None
    if not nonce:
        return None, {"status": "ERROR", "reason": "nonce_missing"}
    return str(nonce), None


def place_order(
    client: httpx.Client,
    property_id: int,
    side: str,
    quantity: float,
    order_type: str,
    price: float = 0.0,
) -> dict:
    nonce, error = fresh_nonce(client)
    if error:
        return error

    payload = {
        "propertyId": int(property_id),
        "price": round(price, 8) if order_type == "LIMIT" else 0,
        "quantity": round(quantity, 8),
        "side": side,
        "type": order_type,
        "timeInForce": "GTC",
        "deadline": 0,
        "nonce": nonce,
    }
    r = client.post(f"{BASE}/api/orders/", json=payload)
    if r.status_code == 403:
        return {"status": "TRADING_GATE_CLOSED", "httpStatus": 403, "body": r.text[:300]}
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("success"):
        return {"status": "ORDER_REJECTED", "response": data}
    return {
        "status": "ORDER_ACCEPTED",
        "orderId": data.get("orderId"),
        "side": side,
        "type": order_type,
        "price": round(price, 8) if order_type == "LIMIT" else 0,
        "quantity": round(quantity, 8),
    }


def passive_price(side: str, bid: float, ask: float) -> float:
    mid = (bid + ask) / 2
    improve = QUOTE_IMPROVEMENT_BPS / 10_000
    if side == "BUY":
        return min(bid * (1 + improve), mid * 0.999999, ask * 0.999999)
    return max(ask * (1 - improve), mid * 1.000001, bid * 1.000001)


def round_elapsed_ratio(now: datetime) -> float:
    total = (END_UTC - START_UTC).total_seconds()
    return max(0.0, min(1.0, (now - START_UTC).total_seconds() / total))


def session_volume_target() -> float:
    total_seconds = (END_UTC - START_UTC).total_seconds()
    five_minute_windows = total_seconds / 300.0
    return ROUND_VOLUME_TARGET / five_minute_windows


def depth_capped_notional(side: str, bid: float, ask: float, bid_qty: float, ask_qty: float, desired: float) -> float:
    # Market BUY consumes asks; market SELL consumes bids. Only use a fraction of visible top-level depth.
    px = ask if side == "BUY" else bid
    qty = ask_qty if side == "BUY" else bid_qty
    if px <= 0:
        return 0.0
    if qty <= 0:
        return min(desired, TAKER_NOTIONAL)
    visible = px * qty
    return max(0.0, min(desired, visible * DEPTH_FRACTION, MAX_TAKER_NOTIONAL))


def maker_attempt(client: httpx.Client, property_id: int, side: str, bid: float, ask: float) -> tuple[bool, float]:
    px = passive_price(side, bid, ask)
    qty = MAKER_NOTIONAL / px
    placed = place_order(client, property_id, side, qty, "LIMIT", px)
    log({"event": "MAKER_ATTEMPT", **placed})
    if placed.get("status") == "TRADING_GATE_CLOSED":
        raise PermissionError("trading_gate_closed")
    if placed.get("status") != "ORDER_ACCEPTED":
        return False, 0.0

    oid = placed.get("orderId")
    time.sleep(MAKER_REST_SECONDS)
    still_open = any(str(o.get("orderId")) == str(oid) for o in active_orders(client))
    if still_open:
        cancel_order(client, oid)
        log({"event": "MAKER_STALE", "orderId": oid})
        return False, 0.0

    # Accepted and no longer active without our cancellation: treat as an inferred fill for pacing.
    log({"event": "MAKER_INFERRED_FILL", "orderId": oid, "side": side, "estimatedVolume": MAKER_NOTIONAL})
    return True, MAKER_NOTIONAL


def taker_round_trip(
    client: httpx.Client,
    property_id: int,
    bid: float,
    ask: float,
    bid_qty: float,
    ask_qty: float,
    desired_notional: float,
) -> tuple[bool, float]:
    # Always cancel resting account orders before crossing. This prevents self-interaction.
    cancel_all_active(client)

    buy_notional = depth_capped_notional("BUY", bid, ask, bid_qty, ask_qty, desired_notional)
    sell_notional = depth_capped_notional("SELL", bid, ask, bid_qty, ask_qty, desired_notional)
    notional = min(buy_notional, sell_notional, MAX_TAKER_NOTIONAL)
    if notional < 50:
        return False, 0.0

    qty = notional / ask
    buy = place_order(client, property_id, "BUY", qty, "MARKET")
    log({"event": "TAKER_BUY", "notional": round(notional, 2), **buy})
    if buy.get("status") == "TRADING_GATE_CLOSED":
        raise PermissionError("trading_gate_closed")
    if buy.get("status") != "ORDER_ACCEPTED":
        return False, 0.0

    time.sleep(0.75)

    # Flatten the newly acquired exposure immediately. Use the same quantity, so a successful pair is near inventory-neutral.
    sell = place_order(client, property_id, "SELL", qty, "MARKET")
    log({"event": "TAKER_SELL", "notional": round(qty * bid, 2), **sell})
    if sell.get("status") == "TRADING_GATE_CLOSED":
        raise PermissionError("trading_gate_closed")
    if sell.get("status") != "ORDER_ACCEPTED":
        log({"status": "KILL_SWITCH", "reason": "round_trip_sell_failed_after_buy"})
        raise RuntimeError("flatten_failed")

    estimated = notional + qty * bid
    return True, estimated


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
            log({"status": "ROUND_ENDED_CLEAN", "ordersCancelled": cleaned})
            return

        cleaned = cancel_all_active(client)
        target = session_volume_target()
        log({
            "event": "SESSION_START",
            "market": MARKET,
            "roundTargetVolume": ROUND_VOLUME_TARGET,
            "sessionTargetVolume": round(target, 2),
            "staleOrdersCancelled": cleaned,
            "mode": "MAKER_FIRST_HYBRID_VOLUME_PACE",
        })

        started = time.monotonic()
        estimated_volume = 0.0
        errors = 0
        empty_books = 0
        cycle = 0
        next_maker_side = "BUY"

        while time.monotonic() - started < SESSION_BUDGET_SECONDS:
            cycle += 1
            current = datetime.now(timezone.utc)
            if current >= END_UTC:
                cancel_all_active(client)
                log({"status": "ROUND_ENDED_DURING_SESSION"})
                return

            try:
                trade, property_id, bid, ask, bid_qty, ask_qty, bid_levels, ask_levels = read_market(client)
                competition_active = bool(trade.get("competitionModeActive", False)) if isinstance(trade, dict) else False

                if property_id is None or bid <= 0 or ask <= bid:
                    empty_books += 1
                    log({
                        "cycle": cycle,
                        "status": "SKIP",
                        "reason": "no_safe_two_sided_book",
                        "bestBid": bid,
                        "bestAsk": ask,
                        "bidLevels": bid_levels,
                        "askLevels": ask_levels,
                        "competitionModeActive": competition_active,
                        "emptyBookStreak": empty_books,
                    })
                    if empty_books >= MAX_EMPTY_BOOKS:
                        cancel_all_active(client)
                        log({"status": "SESSION_PAUSED", "reason": "book_unavailable"})
                        return
                    time.sleep(COOLDOWN_SECONDS)
                    continue

                empty_books = 0
                mid = (bid + ask) / 2
                spread_pct = (ask - bid) / mid * 100
                elapsed_session = time.monotonic() - started
                session_ratio = min(1.0, elapsed_session / SESSION_BUDGET_SECONDS)
                expected_by_now = target * session_ratio
                pace_deficit = max(0.0, expected_by_now - estimated_volume)

                log({
                    "cycle": cycle,
                    "bestBid": bid,
                    "bestAsk": ask,
                    "spreadPct": round(spread_pct, 5),
                    "estimatedSessionVolume": round(estimated_volume, 2),
                    "expectedByNow": round(expected_by_now, 2),
                    "paceDeficit": round(pace_deficit, 2),
                    "roundElapsedPct": round(round_elapsed_ratio(current) * 100, 2),
                })

                # First preference: fee-free maker volume while the book is tradeable.
                maker_filled = False
                if spread_pct <= MAX_MAKER_SPREAD_PCT and estimated_volume < target:
                    maker_filled, maker_vol = maker_attempt(client, property_id, next_maker_side, bid, ask)
                    if maker_filled:
                        estimated_volume += maker_vol
                        next_maker_side = "SELL" if next_maker_side == "BUY" else "BUY"

                # If maker did not fill and the session is behind pace, cross only a very tight spread.
                if (
                    not maker_filled
                    and estimated_volume < target
                    and spread_pct <= MAX_TAKER_SPREAD_PCT
                    and pace_deficit >= TAKER_NOTIONAL
                ):
                    desired = min(MAX_TAKER_NOTIONAL, max(TAKER_NOTIONAL, pace_deficit / 2))
                    ok, taker_vol = taker_round_trip(
                        client, property_id, bid, ask, bid_qty, ask_qty, desired
                    )
                    if ok:
                        estimated_volume += taker_vol

                if estimated_volume >= target:
                    log({"status": "SESSION_TARGET_REACHED", "estimatedSessionVolume": round(estimated_volume, 2), "target": round(target, 2)})
                    break

                errors = 0
                time.sleep(COOLDOWN_SECONDS)

            except PermissionError:
                cancel_all_active(client)
                log({"status": "SESSION_STOPPED", "reason": "competition_not_admitted_or_trading_halted"})
                return
            except httpx.HTTPStatusError as exc:
                errors += 1
                log({"cycle": cycle, "status": "HTTP_ERROR", "code": exc.response.status_code, "body": exc.response.text[:300]})
                if errors >= MAX_ERRORS:
                    cancel_all_active(client)
                    log({"status": "KILL_SWITCH", "reason": "http_errors", "errors": errors})
                    return
                time.sleep(COOLDOWN_SECONDS)
            except Exception as exc:
                errors += 1
                log({"cycle": cycle, "status": "ERROR", "error": str(exc)})
                if errors >= MAX_ERRORS or str(exc) == "flatten_failed":
                    cancel_all_active(client)
                    log({"status": "KILL_SWITCH", "reason": "runtime_or_flatten_error", "errors": errors})
                    return
                time.sleep(COOLDOWN_SECONDS)

        cancel_all_active(client)
        log({
            "status": "ENGINE_SESSION_COMPLETE",
            "market": MARKET,
            "estimatedSessionVolume": round(estimated_volume, 2),
            "sessionTargetVolume": round(target, 2),
            "targetHit": estimated_volume >= target,
            "roundTargetVolume": ROUND_VOLUME_TARGET,
            "safety": "maker-first; taker only when behind pace and spread is tight; market orders paired BUY->SELL; no simultaneous opposing account orders; stale-order cleanup; kill-switch",
        })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log({"status": "FATAL", "error": str(exc)})
        sys.exit(1)
