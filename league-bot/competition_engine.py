from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
import httpx

BASE=os.getenv('LOAF_API_BASE_URL','https://api.loafmarkets.com/api').rstrip('/')
TOKEN=os.getenv('LOAF_API_KEY','')
MARKET=os.getenv('LOAF_TARGET_TOKEN','terafab').lower()
START_UTC=datetime(2026,8,13,2,0,0,tzinfo=timezone.utc)
END_UTC=datetime(2026,8,18,2,0,0,tzinfo=timezone.utc)
SESSION_BUDGET_SECONDS=int(os.getenv('LOAF_ENGINE_SESSION_BUDGET_SECONDS','210'))
MAKER_NOTIONAL=float(os.getenv('LOAF_ENGINE_MAKER_NOTIONAL','1500'))
MAX_MAKER_SPREAD_PCT=float(os.getenv('LOAF_ENGINE_MAX_MAKER_SPREAD_PCT','0.50'))
MAKER_REST_SECONDS=int(os.getenv('LOAF_ENGINE_MAKER_REST_SECONDS','5'))
COOLDOWN_SECONDS=float(os.getenv('LOAF_ENGINE_COOLDOWN_SECONDS','1.5'))
MAX_ERRORS=int(os.getenv('LOAF_ENGINE_MAX_ERRORS','3'))
TARGET_INVENTORY=float(os.getenv('LOAF_ENGINE_TARGET_INVENTORY','20'))
INVENTORY_BAND=float(os.getenv('LOAF_ENGINE_INVENTORY_BAND','5'))
MAX_INVENTORY=float(os.getenv('LOAF_ENGINE_MAX_INVENTORY','50'))
MIN_INVENTORY=float(os.getenv('LOAF_ENGINE_MIN_INVENTORY','0'))


def log(x): print(json.dumps(x,separators=(',',':'),default=str),flush=True)
def fnum(v,d=None):
    try:
        if v is None:return d
        return float(v)
    except:return d

def find_book(node):
    if isinstance(node,dict):
        lower={str(k).lower():k for k in node}
        bk=next((lower[k] for k in ('bids','buyorders','buy_orders') if k in lower),None)
        ak=next((lower[k] for k in ('asks','sellorders','sell_orders') if k in lower),None)
        if bk is not None or ak is not None:
            return node.get(bk,[]) if bk is not None else [],node.get(ak,[]) if ak is not None else []
        for value in node.values():
            found=find_book(value)
            if found is not None:return found
    elif isinstance(node,list):
        for value in node:
            found=find_book(value)
            if found is not None:return found
    return None

def find_flag(node,key):
    if isinstance(node,dict):
        if key in node:return bool(node.get(key))
        for value in node.values():
            found=find_flag(value,key)
            if found is not None:return found
    elif isinstance(node,list):
        for value in node:
            found=find_flag(value,key)
            if found is not None:return found
    return None

def read_market(c):
    r=c.get(f'{BASE}/trade/{MARKET}');r.raise_for_status();trade=r.json()
    found=find_book(trade);bids_raw,asks_raw=found if found is not None else ([],[])
    def pq(x):
        if isinstance(x,dict):return fnum(x.get('price',x.get('px',x.get('p'))),0),fnum(x.get('quantity',x.get('qty',x.get('q'))),0)
        if isinstance(x,(list,tuple)) and x:return fnum(x[0],0),fnum(x[1],0) if len(x)>1 else 0
        return 0,0
    bids=[pq(x) for x in bids_raw or []];asks=[pq(x) for x in asks_raw or []]
    bids=[x for x in bids if x[0]>0];asks=[x for x in asks if x[0]>0]
    bid=max((x[0] for x in bids),default=0);ask=min((x[0] for x in asks),default=0)
    return trade,bid,ask,len(bids),len(asks)

def _market_match(d):
    for key in ('tokenName','token_name','slug','token','asset','name','symbol'):
        v=d.get(key)
        if isinstance(v,str):
            s=v.strip().lower()
            if s==MARKET or MARKET in s or (MARKET=='terafab' and s in ('tera','terafab (tera)')):return True
    return False

def _inventory_from_dict(d):
    if not _market_match(d):return None
    for key in ('units','quantity','balance','tokenBalance','token_balance','currentPosition','current_position','position','holdings'):
        v=fnum(d.get(key))
        if v is not None:return max(0.0,v)
    return None

def find_inventory(node):
    if isinstance(node,dict):
        here=_inventory_from_dict(node)
        if here is not None:return here
        preferred=('positions','tradingPositions','holdings','assets','properties','data','portfolio','result')
        for key in preferred:
            if key in node:
                found=find_inventory(node[key])
                if found is not None:return found
        for key,value in node.items():
            if key not in preferred:
                found=find_inventory(value)
                if found is not None:return found
    elif isinstance(node,list):
        for value in node:
            found=find_inventory(value)
            if found is not None:return found
    return None

def portfolio_inventory(c):
    r=c.get(f'{BASE}/portfolio/');r.raise_for_status();data=r.json()
    inv=find_inventory(data)
    return inv,data

def active_orders(c):
    r=c.get(f'{BASE}/history/orders/active');r.raise_for_status();d=r.json()
    if isinstance(d,list):return d
    if isinstance(d,dict):
        for k in ('activeOrders','orders','data'):
            if isinstance(d.get(k),list):return d[k]
    return []

def cancel_order(c,oid):
    r=c.post(f'{BASE}/orders/cancel',json={'orderId':oid})
    if r.status_code in (200,201,204,404):return True
    # A raced fill/cancel can produce 400. Reconcile instead of failing blindly.
    if r.status_code==400:
        still_open=any(str(o.get('orderId'))==str(oid) for o in active_orders(c))
        if not still_open:return True
    r.raise_for_status();return True

def cancel_all(c):
    n=0
    for o in active_orders(c):
        oid=o.get('orderId')
        if oid is None:continue
        try:
            if cancel_order(c,oid):n+=1
        except Exception as e:log({'event':'CANCEL_ERROR','orderId':oid,'error':str(e)})
    return n

def eligibility(c):
    for path in ('/competition/queue-position','/competition/queue_position'):
        r=c.get(BASE+path)
        if r.status_code==404:continue
        if r.status_code==403:return False,{'httpStatus':403,'body':r.text[:250]}
        r.raise_for_status();return True,r.json()
    return None,{'status':'endpoint_not_resolved'}

def nonce(c):
    r=c.post(f'{BASE}/orders/nonce')
    if r.status_code==403:return None,{'status':'TRADING_GATE_CLOSED','body':r.text[:250]}
    if r.status_code>=400:return None,{'status':'NONCE_HTTP_ERROR','httpStatus':r.status_code,'body':r.text[:500]}
    d=r.json();n=d.get('nonce') if isinstance(d,dict) else None
    return (str(n),None) if n else (None,{'status':'NONCE_MISSING'})

def place(c,side,qty,price):
    n,err=nonce(c)
    if err:return err
    body={'tokenName':MARKET,'quantity':round(qty,1),'side':side,'type':'LIMIT','timeInForce':'GTC','deadline':0,'nonce':n,'price':round(price,2)}
    r=c.post(f'{BASE}/orders/',json=body)
    if r.status_code==403:return {'status':'TRADING_GATE_CLOSED','body':r.text[:500]}
    if r.status_code==503:return {'status':'AMBIGUOUS_503','activeOrdersAfter503':len(active_orders(c))}
    if r.status_code>=400:return {'status':'ORDER_HTTP_ERROR','httpStatus':r.status_code,'body':r.text[:1000],'request':{k:v for k,v in body.items() if k!='nonce'}}
    try:d=r.json()
    except ValueError:d={'raw':r.text[:1000]}
    if not isinstance(d,dict) or not d.get('success'):return {'status':'ORDER_REJECTED','response':d}
    return {'status':'ORDER_ACCEPTED','orderId':d.get('orderId'),'side':side,'quantity':body['quantity'],'price':body['price'],'tokenName':MARKET}

def choose_side(inv,last_side):
    if inv>=MAX_INVENTORY:return 'SELL'
    if inv<=MIN_INVENTORY+0.1:return 'BUY'
    if inv>TARGET_INVENTORY+INVENTORY_BAND:return 'SELL'
    if inv<TARGET_INVENTORY-INVENTORY_BAND:return 'BUY'
    return 'SELL' if last_side=='BUY' else 'BUY'

def quote_once(c,side,bid,ask,inv_before):
    px=bid if side=='BUY' else ask
    if px<=0:return 0,inv_before
    max_qty=(MAX_INVENTORY-inv_before) if side=='BUY' else (inv_before-MIN_INVENTORY)
    qty=min(MAKER_NOTIONAL/px,max(0,max_qty))
    qty=round(qty,1)
    if qty<0.1:
        log({'event':'RISK_SKIP','side':side,'inventory':inv_before,'reason':'inventory_limit'});return 0,inv_before
    p=place(c,side,qty,px);log({'event':'MAKER_ATTEMPT','inventoryBefore':round(inv_before,4),**p})
    if p.get('status')!='ORDER_ACCEPTED':
        if p.get('status') in ('TRADING_GATE_CLOSED','AMBIGUOUS_503','NONCE_HTTP_ERROR','ORDER_HTTP_ERROR'):
            raise RuntimeError(json.dumps(p,separators=(',',':')))
        return 0,inv_before
    oid=p.get('orderId');time.sleep(MAKER_REST_SECONDS)
    if any(str(o.get('orderId'))==str(oid) for o in active_orders(c)):
        cancel_order(c,oid)
    time.sleep(1.0)
    inv_after,_=portfolio_inventory(c)
    if inv_after is None:raise RuntimeError('inventory_unresolved_after_order')
    delta=inv_after-inv_before
    # Count only observed portfolio change; accepted != filled.
    filled_units=max(0,delta) if side=='BUY' else max(0,-delta)
    filled_notional=filled_units*px
    log({'event':'FILL_RECONCILE','side':side,'inventoryBefore':round(inv_before,4),'inventoryAfter':round(inv_after,4),'filledUnits':round(filled_units,4),'filledNotional':round(filled_notional,2)})
    return filled_notional,inv_after

def main():
    if not TOKEN:raise SystemExit('LOAF_API_KEY missing')
    now=datetime.now(timezone.utc);headers={'Authorization':f'Bearer {TOKEN}'}
    with httpx.Client(timeout=15,headers=headers) as c:
        if now<START_UTC:log({'status':'WAITING_FOR_START'});return
        if now>=END_UTC:log({'status':'ROUND_ENDED_CLEAN','ordersCancelled':cancel_all(c)});return
        admitted,elig=eligibility(c);log({'event':'ELIGIBILITY_CHECK','resolved':admitted,'detail':elig})
        if admitted is False:log({'status':'STOP','reason':'competition_not_admitted'});return
        inv,portfolio=portfolio_inventory(c)
        if inv is None:
            log({'status':'STOP','reason':'portfolio_inventory_unresolved','portfolioKeys':list(portfolio.keys()) if isinstance(portfolio,dict) else type(portfolio).__name__});return
        cancel_all(c)
        started=time.monotonic();volume=0.;errors=0;last_side='SELL'
        log({'event':'SESSION_START','market':MARKET,'inventory':round(inv,4),'mode':'passive_inventory_aware_market_making','safety':'portfolio_reconcile + max_inventory + no_taker_loop'})
        while time.monotonic()-started<SESSION_BUDGET_SECONDS:
            try:
                trade,bid,ask,bl,al=read_market(c)
                if find_flag(trade,'competitionModeActive') is not True:
                    log({'status':'WAITING_FOR_COMPETITION'});return
                if bid<=0 or ask<=bid:
                    log({'status':'SKIP','reason':'no_safe_two_sided_book','bidLevels':bl,'askLevels':al});time.sleep(COOLDOWN_SECONDS);continue
                spread=(ask-bid)/((ask+bid)/2)*100
                if spread>MAX_MAKER_SPREAD_PCT:
                    log({'status':'SKIP','reason':'spread_too_wide','spreadPct':round(spread,4)});time.sleep(COOLDOWN_SECONDS);continue
                current,_=portfolio_inventory(c)
                if current is None:raise RuntimeError('portfolio_inventory_unresolved')
                side=choose_side(current,last_side)
                filled,current=quote_once(c,side,bid,ask,current)
                volume+=filled
                if filled>0:last_side=side
                inv=current;errors=0;time.sleep(COOLDOWN_SECONDS)
            except Exception as e:
                errors+=1;log({'event':'ENGINE_ERROR','error':str(e),'errors':errors})
                if errors>=MAX_ERRORS:
                    cancel_all(c);log({'status':'KILL_SWITCH','inventory':round(inv,4)});return
                time.sleep(COOLDOWN_SECONDS)
        cancel_all(c)
        final_inv,_=portfolio_inventory(c)
        log({'status':'SESSION_COMPLETE','observedFilledNotional':round(volume,2),'inventoryStart':round(inv,4),'inventoryEnd':round(final_inv if final_inv is not None else inv,4)})
if __name__=='__main__':main()
