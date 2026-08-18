from __future__ import annotations
import asyncio, json, os, threading, time
from urllib.parse import urlparse
import httpx
import websockets

BASE=os.getenv('LOAF_API_BASE_URL','https://api.loafmarkets.com/api').rstrip('/')
TOKEN=os.getenv('LOAF_API_KEY','')
MARKET=os.getenv('LOAF_TARGET_TOKEN','terafab').lower()
WS_URL=os.getenv('LOAF_WS_URL','')
SESSION_BUDGET_SECONDS=int(os.getenv('LOAF_ENGINE_SESSION_BUDGET_SECONDS','210'))
MAKER_NOTIONAL=float(os.getenv('LOAF_ENGINE_MAKER_NOTIONAL','1500'))
MAX_MAKER_SPREAD_PCT=float(os.getenv('LOAF_ENGINE_MAX_MAKER_SPREAD_PCT','0.50'))
MAKER_REST_SECONDS=float(os.getenv('LOAF_ENGINE_MAKER_REST_SECONDS','5'))
REPRICE_CHECK_SECONDS=float(os.getenv('LOAF_ENGINE_REPRICE_CHECK_SECONDS','0.5'))
REPRICE_MIN_AGE_SECONDS=float(os.getenv('LOAF_ENGINE_REPRICE_MIN_AGE_SECONDS','1.0'))
REPRICE_TICK=float(os.getenv('LOAF_ENGINE_REPRICE_TICK','0.01'))
COOLDOWN_SECONDS=float(os.getenv('LOAF_ENGINE_COOLDOWN_SECONDS','1.5'))
MAX_ERRORS=int(os.getenv('LOAF_ENGINE_MAX_ERRORS','3'))
TARGET_INVENTORY=float(os.getenv('LOAF_ENGINE_TARGET_INVENTORY','20'))
INVENTORY_BAND=float(os.getenv('LOAF_ENGINE_INVENTORY_BAND','5'))
MAX_INVENTORY=float(os.getenv('LOAF_ENGINE_MAX_INVENTORY','50'))
MIN_INVENTORY=float(os.getenv('LOAF_ENGINE_MIN_INVENTORY','0'))
SELL_UTILIZATION=float(os.getenv('LOAF_ENGINE_SELL_UTILIZATION','0.90'))
SELL_RESERVE_UNITS=float(os.getenv('LOAF_ENGINE_SELL_RESERVE_UNITS','0.5'))
WS_STALE_SECONDS=float(os.getenv('LOAF_ENGINE_WS_STALE_SECONDS','4'))

class TradingGateClosed(Exception):
    pass

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
        if bk is not None or ak is not None:return node.get(bk,[]) if bk is not None else [],node.get(ak,[]) if ak is not None else []
        for value in node.values():
            found=find_book(value)
            if found is not None:return found
    elif isinstance(node,list):
        for value in node:
            found=find_book(value)
            if found is not None:return found
    return None

def pq(x):
    if isinstance(x,dict):return fnum(x.get('price',x.get('px',x.get('p'))),0),fnum(x.get('quantity',x.get('qty',x.get('q'))),0)
    if isinstance(x,(list,tuple)) and x:return fnum(x[0],0),fnum(x[1],0) if len(x)>1 else 0
    return 0,0

def book_stats(bids_raw,asks_raw):
    bids=[pq(x) for x in bids_raw or []];asks=[pq(x) for x in asks_raw or []]
    bids=[x for x in bids if x[0]>0];asks=[x for x in asks if x[0]>0]
    return max((x[0] for x in bids),default=0),min((x[0] for x in asks),default=0),len(bids),len(asks)

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

def resolve_ws_url():
    if WS_URL:return WS_URL
    parsed=urlparse(BASE);return f"{'wss' if parsed.scheme=='https' else 'ws'}://{parsed.netloc}/ws"

class LiveOrderBook:
    def __init__(self):
        self.lock=threading.Lock();self.bid=0.;self.ask=0.;self.bl=0;self.al=0;self.updated=0.;self.confirmed=False;self.connected=False;self.stop_evt=threading.Event();self.thread=threading.Thread(target=self._thread_main,name='loaf-orderbook-ws',daemon=True)
    def start(self):self.thread.start()
    def stop(self):self.stop_evt.set()
    def snapshot(self):
        with self.lock:return self.bid,self.ask,self.bl,self.al,self.updated,self.connected,self.confirmed
    def _apply(self,msg):
        if not isinstance(msg,dict) or msg.get('type')!='orderbook_update':return
        bid,ask,bl,al=book_stats(msg.get('bids') or [],msg.get('asks') or [])
        if bid<=0 or ask<=0:return
        with self.lock:self.bid,self.ask,self.bl,self.al,self.updated=bid,ask,bl,al,time.monotonic()
    async def _run(self):
        url=resolve_ws_url();backoff=1.0
        while not self.stop_evt.is_set():
            try:
                async with websockets.connect(url,ping_interval=20,close_timeout=3) as ws:
                    with self.lock:self.connected=True
                    frame={'type':'subscribe','channels':[f'orderbook:{MARKET}']};await ws.send(json.dumps(frame));log({'event':'WS_CONNECTED','url':url,'channel':frame['channels'][0]});backoff=1.0
                    while not self.stop_evt.is_set():
                        try:raw=await asyncio.wait_for(ws.recv(),timeout=3)
                        except asyncio.TimeoutError:continue
                        try:msg=json.loads(raw)
                        except Exception:continue
                        if isinstance(msg,dict) and msg.get('type')=='subscription_confirmed':
                            with self.lock:self.confirmed=True
                            log({'event':'WS_SUBSCRIPTION_CONFIRMED','channel':frame['channels'][0]})
                        self._apply(msg)
            except Exception as e:log({'event':'WS_RECONNECT','error':str(e),'retrySeconds':round(backoff,1)})
            finally:
                with self.lock:self.connected=False
            if self.stop_evt.is_set():break
            await asyncio.sleep(backoff);backoff=min(backoff*2,8)
    def _thread_main(self):
        try:asyncio.run(self._run())
        except Exception as e:log({'event':'WS_THREAD_STOP','error':str(e)})

def read_market_rest(c):
    r=c.get(f'{BASE}/trade/{MARKET}');r.raise_for_status();trade=r.json();found=find_book(trade);bids_raw,asks_raw=found if found is not None else ([],[]);bid,ask,bl,al=book_stats(bids_raw,asks_raw);return trade,bid,ask,bl,al

def read_market(c,live_book):
    trade,rbid,rask,rbl,ral=read_market_rest(c);bid,ask,bl,al,updated,connected,confirmed=live_book.snapshot();age=time.monotonic()-updated if updated else 9999
    if bid>0 and ask>bid and age<=WS_STALE_SECONDS:return trade,bid,ask,bl,al,'websocket',round(age,3)
    return trade,rbid,rask,rbl,ral,'rest_fallback',round(age,3)

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
    r=c.get(f'{BASE}/portfolio/');r.raise_for_status();data=r.json();return find_inventory(data),data

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
    if r.status_code==400:
        if not any(str(o.get('orderId'))==str(oid) for o in active_orders(c)):return True
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
    d=r.json();n=d.get('nonce') if isinstance(d,dict) else None;return (str(n),None) if n else (None,{'status':'NONCE_MISSING'})

def place(c,side,qty,price):
    n,err=nonce(c)
    if err:return err
    body={'tokenName':MARKET,'quantity':round(qty,1),'side':side,'type':'LIMIT','timeInForce':'GTC','deadline':0,'nonce':n,'price':round(price,2)};r=c.post(f'{BASE}/orders/',json=body)
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

def quote_once(c,live_book,side,bid,ask,inv_before,feed_source):
    px=bid if side=='BUY' else ask
    if px<=0:return 0,inv_before
    if side=='SELL':
        cancelled=cancel_all(c)
        if cancelled:time.sleep(0.5)
        refreshed,_=portfolio_inventory(c)
        if refreshed is None:raise RuntimeError('inventory_unresolved_before_sell')
        inv_before=refreshed;available=max(0.0,inv_before-MIN_INVENTORY-SELL_RESERVE_UNITS);max_qty=available*max(0.0,min(1.0,SELL_UTILIZATION))
    else:max_qty=max(0.0,MAX_INVENTORY-inv_before)
    qty=round(min(MAKER_NOTIONAL/px,max_qty),1)
    if qty<0.1:log({'event':'RISK_SKIP','side':side,'inventory':round(inv_before,4),'reason':'inventory_limit'});return 0,inv_before
    p=place(c,side,qty,px);log({'event':'MAKER_ATTEMPT','feed':feed_source,'inventoryBefore':round(inv_before,4),**p})
    if p.get('status')!='ORDER_ACCEPTED':
        if p.get('status')=='ORDER_HTTP_ERROR' and side=='SELL' and 'Insufficient available balance' in str(p.get('body','')):log({'event':'INVENTORY_RESERVED','inventory':round(inv_before,4),'attemptedQty':qty,'action':'skip_without_kill_switch'});return 0,inv_before
        if p.get('status')=='TRADING_GATE_CLOSED':raise TradingGateClosed(str(p.get('body','')))
        if p.get('status') in ('AMBIGUOUS_503','NONCE_HTTP_ERROR','ORDER_HTTP_ERROR'):raise RuntimeError(json.dumps(p,separators=(',',':')))
        return 0,inv_before
    oid=p.get('orderId');placed=time.monotonic();early_reprice=False
    while time.monotonic()-placed<MAKER_REST_SECONDS:
        time.sleep(min(REPRICE_CHECK_SECONDS,max(0.05,MAKER_REST_SECONDS-(time.monotonic()-placed))))
        age=time.monotonic()-placed
        if age<REPRICE_MIN_AGE_SECONDS:continue
        lbid,lask,_,_,updated,connected,confirmed=live_book.snapshot();ws_age=time.monotonic()-updated if updated else 9999
        live_px=lbid if side=='BUY' else lask
        if connected and confirmed and ws_age<=WS_STALE_SECONDS and live_px>0 and abs(live_px-px)>=REPRICE_TICK-1e-9:
            if any(str(o.get('orderId'))==str(oid) for o in active_orders(c)):
                cancel_order(c,oid);early_reprice=True;log({'event':'STALE_QUOTE_REPRICE','orderId':oid,'side':side,'oldPrice':round(px,2),'livePrice':round(live_px,2),'ageSeconds':round(age,2)});break
            break
    if not early_reprice and any(str(o.get('orderId'))==str(oid) for o in active_orders(c)):cancel_order(c,oid)
    time.sleep(0.5)
    inv_after,_=portfolio_inventory(c)
    if inv_after is None:raise RuntimeError('inventory_unresolved_after_order')
    delta=inv_after-inv_before;filled_units=max(0,delta) if side=='BUY' else max(0,-delta);filled_notional=filled_units*px
    log({'event':'FILL_RECONCILE','side':side,'feed':feed_source,'inventoryBefore':round(inv_before,4),'inventoryAfter':round(inv_after,4),'filledUnits':round(filled_units,4),'filledNotional':round(filled_notional,2),'earlyReprice':early_reprice})
    return filled_notional,inv_after

def main():
    if not TOKEN:raise SystemExit('LOAF_API_KEY missing')
    headers={'Authorization':f'Bearer {TOKEN}'};live_book=LiveOrderBook();live_book.start()
    try:
        with httpx.Client(timeout=15,headers=headers) as c:
            admitted,elig=eligibility(c);log({'event':'ELIGIBILITY_CHECK','resolved':admitted,'detail':elig})
            if admitted is False:log({'status':'WAITING_FOR_COMPETITION','reason':'competition_not_admitted_or_gate_closed'});return
            inv,portfolio=portfolio_inventory(c)
            if inv is None:log({'status':'STOP','reason':'portfolio_inventory_unresolved','portfolioKeys':list(portfolio.keys()) if isinstance(portfolio,dict) else type(portfolio).__name__});return
            cancel_all(c);time.sleep(1.0);started=time.monotonic();volume=0.;errors=0;last_side='SELL';session_start_inv=inv;last_feed=None
            log({'event':'SESSION_START','market':MARKET,'inventory':round(inv,4),'mode':'adaptive_passive_inventory_aware_market_making','marketData':'websocket_primary_rest_fallback','safety':'competition_gate + portfolio_reconcile + max_inventory + reserved_inventory_guard + stale_quote_reprice + no_taker_loop'})
            while time.monotonic()-started<SESSION_BUDGET_SECONDS:
                try:
                    trade,bid,ask,bl,al,feed,feed_age=read_market(c,live_book)
                    if feed!=last_feed:log({'event':'MARKET_DATA_SOURCE','source':feed,'wsAgeSeconds':feed_age,'bidLevels':bl,'askLevels':al});last_feed=feed
                    if find_flag(trade,'competitionModeActive') is not True:log({'status':'WAITING_FOR_COMPETITION','reason':'competition_mode_inactive'});return
                    if bid<=0 or ask<=bid:log({'status':'SKIP','reason':'no_safe_two_sided_book','source':feed,'bidLevels':bl,'askLevels':al});time.sleep(COOLDOWN_SECONDS);continue
                    spread=(ask-bid)/((ask+bid)/2)*100
                    if spread>MAX_MAKER_SPREAD_PCT:log({'status':'SKIP','reason':'spread_too_wide','source':feed,'spreadPct':round(spread,4)});time.sleep(COOLDOWN_SECONDS);continue
                    current,_=portfolio_inventory(c)
                    if current is None:raise RuntimeError('portfolio_inventory_unresolved')
                    side=choose_side(current,last_side);filled,current=quote_once(c,live_book,side,bid,ask,current,feed);volume+=filled
                    if filled>0:last_side=side
                    inv=current;errors=0;time.sleep(COOLDOWN_SECONDS)
                except TradingGateClosed as e:
                    cancel_all(c);log({'status':'WAITING_FOR_COMPETITION','reason':'trading_gate_closed','detail':str(e)[:250]});return
                except Exception as e:
                    errors+=1;log({'event':'ENGINE_ERROR','error':str(e),'errors':errors})
                    if errors>=MAX_ERRORS:cancel_all(c);log({'status':'KILL_SWITCH','inventory':round(inv,4)});return
                    time.sleep(COOLDOWN_SECONDS)
            cancel_all(c);final_inv,_=portfolio_inventory(c);bid,ask,bl,al,updated,connected,confirmed=live_book.snapshot();log({'status':'SESSION_COMPLETE','observedFilledNotional':round(volume,2),'inventoryStart':round(session_start_inv,4),'inventoryEnd':round(final_inv if final_inv is not None else inv,4),'wsConnected':connected,'wsConfirmed':confirmed})
    finally:live_book.stop()
if __name__=='__main__':main()
