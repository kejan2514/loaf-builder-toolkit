import { Heart } from 'lucide-react'
import type { PropertyMarket } from '../types'

interface MarketCardProps {
  market: PropertyMarket
  selected?: boolean
  favorite?: boolean
  onSelect?: (market: PropertyMarket) => void
  onToggleFavorite?: (propertyId: number) => void
}

export function MarketCard({ market, selected = false, favorite = false, onSelect, onToggleFavorite }: MarketCardProps) {
  const apr = (market.rentalYieldPercentage * 100).toFixed(2)

  return (
    <article className={`market-card interactive-market-card ${selected ? 'selected-market-card' : ''}`}>
      <button
        type="button"
        className={`favorite-button ${favorite ? 'is-favorite' : ''}`}
        aria-label={favorite ? `Remove ${market.assetName} from favorites` : `Add ${market.assetName} to favorites`}
        onClick={() => onToggleFavorite?.(market.propertyId)}
      >
        <Heart size={17} fill={favorite ? 'currentColor' : 'none'} />
      </button>

      <button type="button" className="market-card-select" onClick={() => onSelect?.(market)}>
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
        <div className="market-card-footer">
          <span>{market.country}</span>
          <span>{selected ? 'Viewing chart' : 'View chart'}</span>
        </div>
      </button>
    </article>
  )
}
