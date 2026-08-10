from __future__ import annotations
import time
from dotenv import load_dotenv
load_dotenv()
from config import Settings
from loaf_client import LoafClient
from strategy import make_quote
from risk import RiskState,can_trade,tier

cfg=Settings(); api=LoafClient(cfg.api_base,cfg.api_key); state=RiskState()

def resolve_property_id():
    if cfg.property_id:return cfg.property_id
    h=api.market_header(cfg.token_name)
    return int(h['propertyId'])

def cancel_ours(property_id:int):
    if not cfg.live_trading:return
    for o in api.active_orders():
        try:
            if int(o.get('propertyId',-1))==property_id:
                api.cancel(int(o['orderId']))
        except Exception as e: print('cancel warning:',e)

def cycle(property_id:int):
    snap=api.trade_snapshot(cfg.token_name)
    q=make_quote(snap,state.inventory,cfg.order_size,cfg.max_inventory,cfg.quote_offset_bps,cfg.max_spread_pct)
    if not q:
        print('skip: no safe two-sided quote'); return
    ok,why=can_trade(state,(q.bid+q.ask)/2,q.size,cfg.max_inventory,cfg.max_notional_per_order,cfg.daily_loss_limit,cfg.max_consecutive_errors)
    if not ok: raise RuntimeError(why)
    bracket,mult=tier(state.cumulative_volume)
    print(f'quote bid={q.bid} ask={q.ask} size={q.size} volume={state.cumulative_volume:,.0f} tier={bracket} {mult}x live={cfg.live_trading}')
    if not cfg.live_trading:return
    cancel_ours(property_id)
    # Two-sided passive quoting. Do not deliberately cross your own orders.
    buy=api.place_limit(property_id,'BUY',q.bid,q.size)
    sell=api.place_limit(property_id,'SELL',q.ask,q.size)
    print('orders:',buy.get('orderId'),sell.get('orderId'))

if __name__=='__main__':
    pid=resolve_property_id(); print(f'Loaf League bot target={cfg.token_name} propertyId={pid}')
    while True:
        try:
            cycle(pid); state.consecutive_errors=0
        except KeyboardInterrupt:
            print('stopped'); break
        except Exception as e:
            state.consecutive_errors+=1; print('error:',e)
            if state.consecutive_errors>=cfg.max_consecutive_errors:
                print('KILL SWITCH: too many consecutive errors'); break
        time.sleep(cfg.loop_seconds)
