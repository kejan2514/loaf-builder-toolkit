import type { TradeResponse } from '../types'

export async function fetchMarkets(): Promise<TradeResponse> {
  const snapshotUrl = `${import.meta.env.BASE_URL}markets.json?ts=${Date.now()}`
  const response = await fetch(snapshotUrl, {
    headers: {
      Accept: 'application/json',
    },
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`Failed to load synced market data: ${response.statusText}`)
  }

  const data = await response.json()
  if (!data || !Array.isArray(data.properties)) {
    throw new Error('Synced market data has an unexpected format')
  }

  return data
}
