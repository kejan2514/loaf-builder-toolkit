import { useEffect, useMemo, useState } from 'react'
import type { PropertyMarket } from '../types'
import { fetchMarkets } from '../services/api'

export function useMarkets(refreshInterval = 30000) {
  const [markets, setMarkets] = useState<PropertyMarket[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)

    try {
      const data = await fetchMarkets()
      setMarkets(data.properties)
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const interval = window.setInterval(load, refreshInterval)
    return () => window.clearInterval(interval)
  }, [refreshInterval])

  const meta = useMemo(() => {
    const totalMarkets = markets.length
    const supportedChains = Array.from(new Set(markets.map((market) => market.country))).length
    const tvl = markets.reduce((sum, market) => sum + market.marketPrice * market.totalTokens, 0)
    const apr = markets.reduce((sum, market) => sum + market.rentalYieldPercentage * 100, 0) / Math.max(totalMarkets, 1)

    return {
      totalMarkets,
      supportedChains,
      tvl,
      apr,
    }
  }, [markets])

  return {
    markets,
    loading,
    error,
    refetch: load,
    ...meta,
  }
}
