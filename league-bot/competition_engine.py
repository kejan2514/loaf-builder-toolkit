from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
import httpx

BASE=os.getenv('LOAF_API_BASE_URL','https://api.loafmarkets.com/api').rstrip('/')
TOKEN=os.getenv('LOAF_API_KEY','')
MARKET=os.getenv('LOAF_TARGET_TOKEN','terafab').lower()
START_UTC=datetime(2026,8,13,2,0,0,tzinfo=timezone.utc)
END_UTC=datetime(2026,8,18,2,0,0,tzinfo=timezone.utc)
ROUND_VOLUME_TARGET=float(os.getenv('LOAF_ENGINE_ROUND_VOLUME_TARGET','35000000'))
SESSION_BUDGET_SECONDS=int(os.getenv('LOAF_ENGINE_SESSION_BUDGET_SECONDS','210'))
MAKER_NOTIONAL=float(os.getenv('LOAF_ENGINE_MAKER_NOTIONAL','3000'))
TAKER_NOTIONAL=float(os.getenv('LOAF_ENGINE_TAKER_NOTIONAL','1250'))
MAX_TAKER_NOTIONAL=float(os.getenv('LOAF_ENGINE_MAX_TAKER_NOTIONAL','2000'))
MAX_MAKER_SPREAD_PCT=float(os.getenv('LOAF_ENGINE_MAX_MAKER_SPREAD_PCT','1.0'))
MAX_TAKER_SPREAD_PCT=float(os.getenv('LOAF_ENGINE_MAX_TAKER_SPREAD_PCT','0.10'))
MAKER_REST_SECONDS=int(os.getenv('LOAF_ENGINE_MAKER_REST_SECONDS','5'))
COOLDOWN_SECONDS=float(os.getenv('LOAF_ENGINE_COOLDOWN_SECONDS','1.5'))
MAX_ERRORS=int(os.getenv('LOAF_ENGINE_MAX_ERRORS','3'))
MAX_EMPTY_BOOKS=int(os.getenv('LOAF_ENGINE_MAX_EMPTY_BOOKS','12'))
DEPTH_FRACTION=float(os.getenv('LOAF_ENGINE_DEPTH_FRACTION','0.30'))

def log(x): print(json.dumps(x,separators=(',',':'),default=str),flush=True)
def fnum(v,d=0.):
    try:return float(v or d)
    except:return d

def as_property_id(v):
    if v is None or isinstance(v,bool):return None
    try:
        n=int(v);return n if n>=0 else None
    except:return None

def find_property_id(node,market=None):
    if isinstance(node,dict):
        normalized={str(k).lower().replace('_',''):k for k in node}
        for candidate in ('propertyid','propertyidentifier'):
            key=normalized.get(candidate)
            if key is not None:
                parsed=as_property_id(node.get(key))
                if parsed is not None:return parsed
        if market:
            names=[]
            for key in ('tokenName','token_name','token','symbol','slug','name'):
                v=node.get(key)
                if isinstance(v,str):names.append(v.strip().lower())
            if market.strip().lower() in names:
                for key in ('id','property','property_id'):
                    if key in node:
                        parsed=as_property_id(node.get(key))
                        if parsed is not None:return parsed
        preferred=('data','result','market','property','header','payload')
        for key in preferred:
            if key in node:
                found=find_property_id(node[key],market)
                if found is not None:return found
        for key,value in node.items():
            if key not in preferred:
                found=find_property_id(value,market)
                if found is not None:return found
    elif isinstance(node,list):
        for value in node:
            found=find_property_id(value,market)
            if found is not None:return found
    return None

def find_book(node):
    if isinstance(node,dict):
        lower={str(k).lower():k for k in node}
        bk=next((lower[k] for k in ('bids','buyorders','buy_orders') if k in lower),None)
        ak=next((lower[k] for k in ('asks','sellorders','sell_orders') if k in lower),None)
        if bk is not None or ak is not None:return node.get(bk,[]) if bk is not None else [],node.get(ak,[]) if ak is not None else []
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

def resolve_property_id(c,header,trade=None):
    env=os.getenv('LOAF_PROPERTY_ID')
    if env:
        parsed=as_property_id(env)
        if parsed is not None:return parsed,'env'
    for source,payload in (('info_header',header),('trade_snapshot',trade)):
        if payload is not None:
            found=find_property_id(payload,MARKET)
            if found is not None:return found,source
    try:
        r=c.get(f'{BASE}/trade')
        if r.status_code<400:
            found=find_property_id(r.json(),MARKET)
            if found is not None:return found,'trade_list'
    except (httpx.HTTPError,ValueError):pass
    return None,'unresolved'

def read_market(c):
    h=c.get(f'{BASE}/info/{MARKET}/header'); h.raise_for_status(); header=h.json()
    t=c.get(f'{BASE}/trade/{MARKET}'); t.raise_for_status(); trade=t.json()
    property_id,source=resolve_property_id(c,header,trade)
    if property_id is None:raise RuntimeError('propertyId_unresolved')
    found=find_book(trade); bids_raw,asks_raw=found if found is not None else ([],[])
    def pq(x):
        if isinstance(x,dict): return fnum(x.get('price',x.get('px',x.get('p')))),fnum(x.get('quantity',x.get('qty',x.get('q'))))
        return (fnum(x[0]),fnum(x[1]) if len(x)>1 else 0) if isinstance(x,(list,tuple)) and x else (0,0)
    bids=[pq(x) for x in bids_raw or []]; asks=[pq(x) for x in asks_raw or []]
    bids=[x for x in bids if x[0]>0]; asks=[x for x in asks if x[0]>0]
    bid,bq=max(bids,key=lambda x:x[0]) if bids else (0,0); ask,aq=min(asks,key=lambda x:x[0]) if asks else (0,0)
    return int(property_id),source,trade,bid,ask,bq,aq,len(bids),len(asks)

def active_orders(c):
    r=c.get(f'{BASE}/history/orders/active'); r.raise_for_status(); d=r.json()
    if isinstance(d,list):return d
    if isinstance(d,dict):
        for k in ('activeOrders','orders','data'):
            if isinstance(d.get(k),list):return d[k]
    return []

def cancel_order(c,oid):
    r=c.post(f'{BASE}/orders/cancel',json={'orderId':oid})
    if r.status_code!=404:r.raise_for_status()
def cancel_all(c):
    n=0
    for o in active_orders(c):
        if o.get('orderId') is not None:
            try:cancel_order(c,o['orderId']);n+=1
            except Exception as e:log({'event':'CANCEL_ERROR','error':str(e)})
    return n

def eligibility(c):
    for path in ('/competition/queue-position','/competition/queue_position'):
        try:
            r=c.get(BASE+path)
            if r.status_code==404:continue
            if r.status_code==403:return False,{'httpStatus':403,'body':r.text[:250]}
            r.raise_for_status(); d=r.json(); return True,d
        except httpx.HTTPStatusError as e:
            if e.response.status_code==404:continue
            raise
    return None,{'status':'endpoint_not_resolved'}

def nonce(c):
    r=c.post(f'{BASE}/orders/nonce')
    if r.status_code==403:return None,None,{'status':'TRADING_GATE_CLOSED','body':r.text[:250]}
    if r.status_code>=400:return None,None,{'status':'NONCE_HTTP_ERROR','httpStatus':r.status_code,'body':r.text[:500]}
    d=r.json(); n=d.get('nonce') if isinstance(d,dict) else None
    deadline=d.get('deadline',0) if isinstance(d,dict) else 0
    return (str(n),deadline,None) if n else (None,deadline,{'status':'ERROR','reason':'nonce_missing','body':d})

def place(c,property_id,side,qty,typ,price=0.):
    n,_nonce_deadline,err=nonce(c)
    if err:return err
    body={'tokenName':MARKET,'quantity':round(qty,1),'side':side,'type':typ,'timeInForce':'GTC','deadline':0,'nonce':n,'price':round(price,2) if typ=='LIMIT' else 0}
    r=c.post(f'{BASE}/orders/',json=body)
    if r.status_code==403:return {'status':'TRADING_GATE_CLOSED','body':r.text[:500]}
    if r.status_code==503:return {'status':'AMBIGUOUS_503','activeOrdersAfter503':len(active_orders(c))}
    if r.status_code>=400:return {'status':'ORDER_HTTP_ERROR','httpStatus':r.status_code,'body':r.text[:1000],'request':{k:v for k,v in body.items() if k!='nonce'},'resolvedPropertyId':int(property_id)}
    try:d=r.json()
    except ValueError:d={'raw':r.text[:1000]}
    if not isinstance(d,dict) or not d.get('success'):return {'status':'ORDER_REJECTED','response':d}
    return {'status':'ORDER_ACCEPTED','orderId':d.get('orderId'),'side':side,'type':typ,'quantity':body['quantity'],'price':body['price'],'propertyId':int(property_id),'tokenName':MARKET}

def passive(side,bid,ask):return round(bid if side=='BUY' else ask,2)
def target5():return ROUND_VOLUME_TARGET/((END_UTC-START_UTC).total_seconds()/300)
def depth_notional(side,bid,ask,bq,aq,desired):
    px,q=(ask,aq) if side=='BUY' else (bid,bq)
    if px<=0:return 0
    return min(desired,MAX_TAKER_NOTIONAL,px*q*DEPTH_FRACTION) if q>0 else min(desired,TAKER_NOTIONAL)

def maker(c,property_id,side,bid,ask):
    px=passive(side,bid,ask); p=place(c,property_id,side,MAKER_NOTIONAL/px,'LIMIT',px); log({'event':'MAKER_ATTEMPT',**p})
    if p.get('status') in ('TRADING_GATE_CLOSED','AMBIGUOUS_503','NONCE_HTTP_ERROR'):raise RuntimeError(json.dumps(p,separators=(',',':')))
    if p.get('status')=='ORDER_HTTP_ERROR':
        # A BUY fill can take a moment to become sellable inventory. Do not trip the
        # kill switch on that expected settlement window; keep the side on SELL and retry later.
        if side=='SELL' and 'Insufficient available balance' in str(p.get('body','')):
            log({'event':'INVENTORY_NOT_SETTLED','action':'WAIT_AND_RETRY_SELL','propertyId':property_id})
            time.sleep(max(COOLDOWN_SECONDS,2.0));return 0
        raise RuntimeError(json.dumps(p,separators=(',',':')))
    if p.get('status')!='ORDER_ACCEPTED':return 0
    oid=p.get('orderId');time.sleep(MAKER_REST_SECONDS)
    if any(str(o.get('orderId'))==str(oid) for o in active_orders(c)):
        cancel_order(c,oid);return 0
    # Order disappeared from active orders: treat as filled, but allow account inventory
    # state to settle before attempting the opposite side.
    time.sleep(2.0)
    return MAKER_NOTIONAL

def taker_pair(c,property_id,bid,ask,bq,aq,desired):
    cancel_all(c); n=min(depth_notional('BUY',bid,ask,bq,aq,desired),depth_notional('SELL',bid,ask,bq,aq,desired))
    if n<50:return 0
    qty=n/ask; b=place(c,property_id,'BUY',qty,'MARKET');log({'event':'TAKER_BUY',**b})
    if b.get('status')!='ORDER_ACCEPTED':raise RuntimeError(json.dumps(b,separators=(',',':')))
    time.sleep(2.0); s=place(c,property_id,'SELL',qty,'MARKET');log({'event':'TAKER_SELL',**s})
    if s.get('status')!='ORDER_ACCEPTED':raise RuntimeError(json.dumps(s,separators=(',',':')))
    return n+qty*bid

def main():
    if not TOKEN:raise SystemExit('LOAF_API_KEY missing')
    now=datetime.now(timezone.utc); headers={'Authorization':f'Bearer {TOKEN}'}
    with httpx.Client(timeout=15,headers=headers) as c:
        if now<START_UTC:log({'status':'WAITING_FOR_START','officialStartUtc':START_UTC.isoformat()});return
        if now>=END_UTC:log({'status':'ROUND_ENDED_CLEAN','ordersCancelled':cancel_all(c)});return
        admitted,elig=eligibility(c);log({'event':'ELIGIBILITY_CHECK','resolved':admitted,'detail':elig})
        if admitted is False:log({'status':'STOP','reason':'competition_not_admitted'});return
        cancel_all(c);tgt=target5();started=time.monotonic();vol=0.;errors=empty=0;side='BUY';property_id=None
        log({'event':'SESSION_START','market':MARKET,'sessionTargetVolume':round(tgt,2),'protocol':'tokenName-order-rest','safety':'fresh_nonce + reconcile_503 + competition_gate + inventory_settlement_guard'})
        while time.monotonic()-started<SESSION_BUDGET_SECONDS:
            try:
                property_id,property_source,trade,bid,ask,bq,aq,bl,al=read_market(c)
                competition_active=find_flag(trade,'competitionModeActive')
                if competition_active is not True:
                    log({'status':'WAITING_FOR_COMPETITION','competitionModeActive':competition_active,'propertyId':property_id,'propertyIdSource':property_source});return
                if bid<=0 or ask<=bid:
                    empty+=1;log({'status':'SKIP','reason':'no_safe_two_sided_book','propertyId':property_id,'propertyIdSource':property_source,'bidLevels':bl,'askLevels':al})
                    if empty>=MAX_EMPTY_BOOKS:return
                    time.sleep(COOLDOWN_SECONDS);continue
                empty=0;spread=(ask-bid)/((ask+bid)/2)*100;ratio=min(1,(time.monotonic()-started)/SESSION_BUDGET_SECONDS);deficit=max(0,tgt*ratio-vol)
                if spread<=MAX_MAKER_SPREAD_PCT:
                    filled=maker(c,property_id,side,bid,ask)
                    vol+=filled
                    if filled>0:side='SELL' if side=='BUY' else 'BUY'
                if deficit>TAKER_NOTIONAL and spread<=MAX_TAKER_SPREAD_PCT:vol+=taker_pair(c,property_id,bid,ask,bq,aq,min(MAX_TAKER_NOTIONAL,max(TAKER_NOTIONAL,deficit/2)))
                errors=0;time.sleep(COOLDOWN_SECONDS)
            except Exception as e:
                errors+=1;log({'event':'ENGINE_ERROR','error':str(e),'errors':errors,'propertyId':property_id})
                if errors>=MAX_ERRORS:cancel_all(c);log({'status':'KILL_SWITCH'});return
                time.sleep(COOLDOWN_SECONDS)
        cancel_all(c);log({'status':'SESSION_COMPLETE','estimatedVolume':round(vol,2),'target':round(tgt,2),'propertyId':property_id})
if __name__=='__main__':main()
