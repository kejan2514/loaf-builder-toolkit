import type { TradeResponse } from '../types'

const BASE_URL = 'https://api.loafmarkets.com'

export async function fetchMarkets(): Promise<TradeResponse> {
  const response = await fetch(`${BASE_URL}/api/trade`, {
    headers: {
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to load market data: ${response.statusText}`)
  }

  return response.json()
}
