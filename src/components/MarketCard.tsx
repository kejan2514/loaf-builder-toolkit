import type { PropertyMarket } from '../types'

interface MarketCardProps {
  market: PropertyMarket
}

export function MarketCard({ market }: MarketCardProps) {
  const apr = (market.rentalYieldPercentage * 100).toFixed(2)
  return (
    <article className="market-card">
      <div className="market-card-header">
        <div>
          <p>{market.assetName}</p>
          <strong>{market.ticker}</strong>
        </div>
        <span className="market-status">{market.status}</span>
      </div>
      <div className="market-card-body">
        <div>
          <span>Price</span>
          <strong>${market.marketPrice.toFixed(2)}</strong>
        </div>
        <div>
          <span>24h Volume</span>
          <strong>${market.volume24h.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
        </div>
        <div>
          <span>APR</span>
          <strong>{apr}%</strong>
        </div>
      </div>
    </article>
  )
}
