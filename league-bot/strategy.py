from dataclasses import dataclass

@dataclass
class Quote:
    bid: float
    ask: float
    size: float


def _levels(snapshot:dict, name:str):
    book=snapshot.get('orderBook') or snapshot.get('orderbook') or snapshot
    return book.get(name,[]) if isinstance(book,dict) else []


def make_quote(snapshot:dict, inventory:float, base_size:float, max_inventory:float, offset_bps:float, max_spread_pct:float) -> Quote | None:
    bids=_levels(snapshot,'bids'); asks=_levels(snapshot,'asks')
    if not bids or not asks: return None
    best_bid=float(bids[0].get('price')); best_ask=float(asks[0].get('price'))
    if best_bid<=0 or best_ask<=best_bid: return None
    mid=(best_bid+best_ask)/2
    spread_pct=(best_ask-best_bid)/mid*100
    if spread_pct>max_spread_pct: return None
    tick=mid*(offset_bps/10000)
    skew=max(-1,min(1, inventory/max_inventory if max_inventory else 0))
    # Long inventory shifts both quotes lower; short inventory shifts them higher.
    skew_px=mid*(skew*offset_bps/10000)
    bid=min(best_ask-tick, best_bid+tick-skew_px)
    ask=max(best_bid+tick, best_ask-tick-skew_px)
    if bid>=ask: return None
    size=max(0.1,base_size*(1-0.5*abs(skew)))
    return Quote(round(bid,8),round(ask,8),round(size,6))
