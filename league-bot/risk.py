from dataclasses import dataclass

@dataclass
class RiskState:
    inventory: float = 0.0
    realized_pnl: float = 0.0
    cumulative_volume: float = 0.0
    consecutive_errors: int = 0


def can_trade(state:RiskState, price:float, size:float, max_inventory:float, max_notional:float, daily_loss_limit:float, max_errors:int) -> tuple[bool,str]:
    if state.realized_pnl <= -abs(daily_loss_limit): return False,'daily loss limit reached'
    if abs(state.inventory) >= max_inventory: return False,'inventory cap reached'
    if price*size > max_notional: return False,'order notional cap exceeded'
    if state.consecutive_errors >= max_errors: return False,'error kill switch reached'
    return True,'ok'


def tier(volume:float) -> tuple[str,int]:
    if volume>=30_000_000:return '$30M+',5
    if volume>=20_000_000:return '$20M-$30M',4
    if volume>=10_000_000:return '$10M-$20M',3
    if volume>=5_000_000:return '$5M-$10M',2
    return '$0-$5M',1
