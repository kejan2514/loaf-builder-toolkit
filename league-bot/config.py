from pydantic import BaseModel
import os

class Settings(BaseModel):
    api_base: str = os.getenv('LOAF_API_BASE','https://api.loafmarkets.com').rstrip('/')
    api_key: str = os.getenv('LOAF_API_KEY','')
    token_name: str = os.getenv('LOAF_TOKEN_NAME','terafab')
    property_id: int | None = int(os.environ['LOAF_PROPERTY_ID']) if os.getenv('LOAF_PROPERTY_ID') else None
    live_trading: bool = os.getenv('LOAF_LIVE_TRADING','false').lower() == 'true'
    loop_seconds: float = float(os.getenv('LOAF_LOOP_SECONDS','5'))
    order_size: float = float(os.getenv('LOAF_ORDER_SIZE','2'))
    max_inventory: float = float(os.getenv('LOAF_MAX_INVENTORY','40'))
    max_notional_per_order: float = float(os.getenv('LOAF_MAX_NOTIONAL_PER_ORDER','1500'))
    max_spread_pct: float = float(os.getenv('LOAF_MAX_SPREAD_PCT','1.5'))
    quote_offset_bps: float = float(os.getenv('LOAF_QUOTE_OFFSET_BPS','2'))
    daily_loss_limit: float = float(os.getenv('LOAF_DAILY_LOSS_LIMIT','3000'))
    max_consecutive_errors: int = int(os.getenv('LOAF_MAX_CONSECUTIVE_ERRORS','5'))
    target_volume: float = float(os.getenv('LOAF_TARGET_VOLUME','30000000'))
