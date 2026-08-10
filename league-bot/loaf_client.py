from __future__ import annotations
import httpx

class LoafClient:
    def __init__(self, base: str, api_key: str):
        self.base = base.rstrip('/')
        self.client = httpx.Client(timeout=10.0, headers={'Authorization': f'Bearer {api_key}'} if api_key else {})

    def market_header(self, token: str) -> dict:
        r = self.client.get(f'{self.base}/api/info/{token}/header')
        r.raise_for_status(); return r.json()

    def trade_snapshot(self, token: str) -> dict:
        r = self.client.get(f'{self.base}/api/trade/{token}')
        r.raise_for_status(); return r.json()

    def active_orders(self) -> list[dict]:
        r = self.client.get(f'{self.base}/api/history/orders/active')
        r.raise_for_status(); data=r.json(); return data if isinstance(data,list) else data.get('orders',[])

    def nonce(self) -> dict:
        r = self.client.post(f'{self.base}/api/orders/nonce')
        r.raise_for_status(); return r.json()

    def place_limit(self, property_id:int, side:str, price:float, quantity:float) -> dict:
        nonce = self.nonce()
        payload = {'propertyId':property_id,'price':round(price,8),'quantity':quantity,'side':side,'type':'LIMIT','timeInForce':'GTC','deadline':nonce.get('deadline',0),'nonce':nonce['nonce']}
        r = self.client.post(f'{self.base}/api/orders/',json=payload)
        r.raise_for_status(); return r.json()

    def cancel(self, order_id:int) -> dict:
        r = self.client.post(f'{self.base}/api/orders/cancel',json={'orderId':order_id})
        r.raise_for_status(); return r.json()
