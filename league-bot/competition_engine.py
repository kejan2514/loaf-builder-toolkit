from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import httpx

# Official docs use a REST base that includes /api and order creation keyed by lowercase tokenName.
BASE = os.getenv("LOAF_API_BASE_URL", "https://api.loafmarkets.com/api").rstrip("/")
TOKEN = os.getenv("LOAF_API_KEY", "")
MARKET = os.getenv("LOAF_TARGET_TOKEN", os.getenv("LOAF_TOKEN_NAME", "terafab")).lower()
START_UTC = datetime(2026, 8, 13, 2, 0, 0, tzinfo=timezone.utc)
END_UTC = datetime(2026, 8, 18, 2, 0, 0, tzinfo=timezone.utc)
ROUND_VOLUME_TARGET = float(os.getenv("LOAF_ENGINE_ROUND_VOLUME_TARGET", "35000000"))
SESSION_BUDGET_SECONDS = int(os.getenv("LOAF_ENGINE_SESSION_BUDGET_SECONDS", "210"))
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


def log(x: dict) -> None:
    print(json.dumps(x, separators=(",", ":"), default=str), flush=True)


def fnum(v, d=0.0):
    try: return float(v or d)
    except (TypeError, ValueError): return d


def read_market(c):
    h = c.get(f"{BASE}/info/{MARKET}/header"); h.raise_for_status(); header = h.json()
    t = c.get(f"{BASE}/trade/{MARKET}"); t.raise_for_status(); trade = t.json()
    book = trade.get("orderBook") or {}
    bids_raw, asks_raw = book.get("bids") or [], book.get("asks") or []
    def pq(x):
        if isinstance(x, dict): return fnum(x.get("price")), fnum(x.get("quantity"))
        return (fnum(x[0]), fnum(x[1]) if len(x)>1 else 0) if isinstance(x,(list,tuple)) and x else (0,0)
    bids=[pq(x) for x in bids_raw if pq(x)[0]>0]; asks=[pq(x) for x in asks_raw if pq(x)[0]>0]
    bid,bq=max(bids,key=lambda x:x[0]) if bids else (0,0); ask,aq=min(asks,key=lambda x:x[0]) if asks else (0,0)
    return trade,bid,ask,bq,aq,len(bids_raw),len(asks_raw),header


def active_orders(c):
    r=c.get(f"{BASE}/history/orders/active"); r.raise_for_status(); raw=r.json()
    if isinstance(raw,list): return raw
    if isinstance(raw,dict):
        for k in ("activeOrders","orders","data"):
            if isinstance(raw.get(k),list): return raw[k]
    return []


def cancel_order(c, oid):
    r=c.post(f"{BASE}/orders/cancel",json={"orderId":oid})
    if r.status_code==404: return
    r.raise_for_status(); log({"event":"CANCEL","orderId":oid})


def cancel_all(c):
    n=0
    for o in active_orders(c):
        if o.get("orderId") is not None:
            try: cancel_order(c,o["orderId"]); n+=1
            except Exception as e: log({"event":"CANCEL_ERROR","error":str(e)})
    return n


def nonce(c):
    r=c.post(f"{BASE}/orders/nonce")
    if r.status_code==403: return None,{"status":"TRADING_GATE_CLOSED","body":r.text[:300]}
    r.raise_for_status(); d=r.json(); n=d.get("nonce") if isinstance(d,dict) else None
    return (str(n),None) if n else (None,{"status":"ERROR","reason":"nonce_missing"})


def place(c, side, qty, typ, price=0.0):
    n,err=nonce(c)
    if err:return err
    # Official protocol: tokenName, not propertyId. Fresh nonce for every order.
    body={"tokenName":MARKET,"quantity":round(qty,8),"side":side,"type":typ,"timeInForce":"GTC","deadline":0,"nonce":n}
    if typ=="LIMIT": body["price"]=round(price,8)
    else: body["price"]=0
    r=c.post(f"{BASE}/orders",json=body)
    if r.status_code==403:return {"status":"TRADING_GATE_CLOSED","body":r.text[:300]}
    if r.status_code==503:return {"status":"AMBIGUOUS_503","body":r.text[:300]}
    r.raise_for_status(); d=r.json()
    if not isinstance(d,dict) or not d.get("success"):return {"status":"ORDER_REJECTED","response":d}
    return {"status":"ORDER_ACCEPTED","orderId":d.get("orderId"),"side":side,"type":typ,"quantity":round(qty,8),"price":round(price,8) if typ=="LIMIT" else 0}


def passive(side,bid,ask):
    mid=(bid+ask)/2; imp=QUOTE_IMPROVEMENT_BPS/10000
    return min(bid*(1+imp),mid*.999999,ask*.999999) if side=="BUY" else max(ask*(1-imp),mid*1.000001,bid*1.000001)


def target5(): return ROUND_VOLUME_TARGET/((END_UTC-START_UTC).total_seconds()/300)


def depth_notional(side,bid,ask,bq,aq,desired):
    px,q=(ask,aq) if side=="BUY" else (bid,bq)
    if px<=0:return 0
    return min(desired,MAX_TAKER_NOTIONAL,px*q*DEPTH_FRACTION) if q>0 else min(desired,TAKER_NOTIONAL)


def maker(c,side,bid,ask):
    px=passive(side,bid,ask); qty=MAKER_NOTIONAL/px; p=place(c,side,qty,"LIMIT",px); log({"event":"MAKER_ATTEMPT",**p})
    if p.get("status") in ("TRADING_GATE_CLOSED","AMBIGUOUS_503"): raise RuntimeError(p["status"])
    if p.get("status")!="ORDER_ACCEPTED":return 0
    oid=p.get("orderId"); time.sleep(MAKER_REST_SECONDS)
    if any(str(o.get("orderId"))==str(oid) for o in active_orders(c)):
        cancel_order(c,oid); return 0
    return MAKER_NOTIONAL


def taker_pair(c,bid,ask,bq,aq,desired):
    cancel_all(c); n=min(depth_notional("BUY",bid,ask,bq,aq,desired),depth_notional("SELL",bid,ask,bq,aq,desired))
    if n<50:return 0
    qty=n/ask; b=place(c,"BUY",qty,"MARKET"); log({"event":"TAKER_BUY",**b})
    if b.get("status")!="ORDER_ACCEPTED": raise RuntimeError(b.get("status","buy_failed"))
    time.sleep(.75); s=place(c,"SELL",qty,"MARKET"); log({"event":"TAKER_SELL",**s})
    if s.get("status")!="ORDER_ACCEPTED": raise RuntimeError("flatten_failed")
    return n+qty*bid


def main():
    if not TOKEN: raise SystemExit("LOAF_API_KEY missing")
    now=datetime.now(timezone.utc); headers={"Authorization":f"Bearer {TOKEN}"}
    with httpx.Client(timeout=15,headers=headers) as c:
        if now<START_UTC: log({"status":"WAITING_FOR_START"}); return
        if now>=END_UTC: log({"status":"ROUND_ENDED_CLEAN","ordersCancelled":cancel_all(c)}); return
        cancel_all(c); tgt=target5(); started=time.monotonic(); vol=0.; errors=empty=0; side="BUY"
        log({"event":"SESSION_START","market":MARKET,"sessionTargetVolume":round(tgt,2),"protocol":"official-tokenName-rest"})
        while time.monotonic()-started<SESSION_BUDGET_SECONDS:
            try:
                trade,bid,ask,bq,aq,bl,al,header=read_market(c)
                if bid<=0 or ask<=bid:
                    empty+=1; log({"status":"SKIP","reason":"no_safe_two_sided_book","bidLevels":bl,"askLevels":al})
                    if empty>=MAX_EMPTY_BOOKS:return
                    time.sleep(COOLDOWN_SECONDS); continue
                empty=0; spread=(ask-bid)/((ask+bid)/2)*100
                ratio=min(1,(time.monotonic()-started)/SESSION_BUDGET_SECONDS); deficit=max(0,tgt*ratio-vol)
                if spread<=MAX_MAKER_SPREAD_PCT:
                    vol+=maker(c,side,bid,ask); side="SELL" if side=="BUY" else "BUY"
                if deficit>TAKER_NOTIONAL and spread<=MAX_TAKER_SPREAD_PCT:
                    vol+=taker_pair(c,bid,ask,bq,aq,min(MAX_TAKER_NOTIONAL,max(TAKER_NOTIONAL,deficit/2)))
                errors=0; time.sleep(COOLDOWN_SECONDS)
            except Exception as e:
                errors+=1; log({"event":"ENGINE_ERROR","error":str(e),"errors":errors})
                if errors>=MAX_ERRORS:
                    cancel_all(c); log({"status":"KILL_SWITCH"}); return
                time.sleep(COOLDOWN_SECONDS)
        cancel_all(c); log({"status":"SESSION_COMPLETE","estimatedVolume":round(vol,2),"target":round(tgt,2)})

if __name__=="__main__": main()
