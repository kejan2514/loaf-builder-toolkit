# Loaf League Volume Bot

A competition-focused, risk-controlled market-making bot for Loaf Markets League rounds.

## Goals

- Grow legitimate traded volume without wash trading or self-trading.
- Prefer maker liquidity because the current Round 1 screen shows 0% maker and 0.1% taker fees.
- Protect mock capital with inventory caps, spread filters, loss limits and a kill switch.
- Track progress toward the League volume multiplier tiers.

> No ranking is guaranteed. The bot is designed to improve execution quality and consistency while following platform rules.

## Round 1 defaults

The UI currently describes Round 1 as a five-day `Volumemaxxing` round with $100,000 mock starting capital. Volume multipliers shown in the League UI are 1x up to $5M, 2x from $5M-$10M, 3x from $10M-$20M, 4x from $20M-$30M and 5x above $30M. Configure these values if Loaf changes the rules.

## Safety model

The bot does **not** intentionally match against its own orders. It avoids blind market-order loops and only quotes when a valid two-sided book exists. Live trading is disabled by default.

## Setup

```bash
cd league-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Create an API key from Loaf's API settings and put it only in `.env` or a secret store. Never commit it.

## Run dry mode

```bash
python bot.py
```

To permit live API order placement, set:

```bash
LOAF_LIVE_TRADING=true
```

Start with tiny sizes and monitor the first session manually.

## Strategy

Each cycle the bot:

1. Loads the target market and order book.
2. Rejects empty/wide/abnormal books.
3. Computes inventory-aware bid and ask quotes near the touch.
4. Uses small, bounded order size.
5. Cancels stale orders before replacement.
6. Stops when risk limits are hit.
7. Reports estimated volume-tier progress.

The goal is sustained legitimate participation, not spam.
