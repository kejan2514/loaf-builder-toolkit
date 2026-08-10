from __future__ import annotations

import os
import sys
import httpx

BASE = os.getenv("LOAF_API_BASE", "https://api.loafmarkets.com").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TOKEN_NAME", "terafab")


def fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(code)


def main() -> None:
    if not TOKEN:
        fail("LOAF_API_KEY is missing. Configure the LOAF_API_TOKEN repository secret.")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15.0, headers=headers) as client:
        print(f"Testing Loaf API connection: {BASE}")
        print(f"Target market: {MARKET}")

        market = client.get(f"{BASE}/api/info/{MARKET}/header")
        print(f"Market metadata HTTP {market.status_code}")
        market.raise_for_status()
        header = market.json()
        property_id = header.get("propertyId")
        print(f"Market resolved: propertyId={property_id}")

        orders = client.get(f"{BASE}/api/history/orders/active")
        print(f"Authenticated history HTTP {orders.status_code}")
        orders.raise_for_status()
        data = orders.json()
        active = data if isinstance(data, list) else data.get("orders", []) if isinstance(data, dict) else []
        print(f"Authenticated API access confirmed. Active orders visible: {len(active)}")

    print("SAFE TEST PASSED: no nonce requested, no order placed, no order cancelled.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        response = exc.response
        print(f"HTTP failure: {response.status_code}")
        # Never print request headers or the API token.
        body = response.text[:300].replace(TOKEN, "***") if TOKEN else response.text[:300]
        print(f"Response: {body}")
        sys.exit(1)
