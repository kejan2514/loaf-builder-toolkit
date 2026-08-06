import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChevronRight, RefreshCw, Search, Sparkles } from 'lucide-react'
import { Header } from './components/Header'
import { Footer } from './components/Footer'
import { StatCard } from './components/StatCard'
import { MarketCard } from './components/MarketCard'
import { Loading } from './components/Loading'
import { ErrorBanner } from './components/ErrorBanner'
import { useMarkets } from './hooks/useMarkets'

const docsLinks = [
  { label: 'Official Documentation', href: 'https://docs.loafmarkets.com/en/' },
  { label: 'API Reference', href: 'https://docs.loafmarkets.com/en/api-reference/' },
  { label: 'Trading Bot Guide', href: 'https://docs.loafmarkets.com/en/guides/building-a-trading-bot/' },
]

type SortOption = 'volume' | 'apr' | 'price-high' | 'price-low'

function App() {
  const { markets, loading, error, totalMarkets, supportedChains, tvl, apr, refetch } = useMarkets(30000)
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState<SortOption>('volume')
  const chartMarket = markets[0]

  const chartData = useMemo(() => {
    return chartMarket?.candlesticks.slice(-7).map((candle) => ({
      date: new Date(candle.time * 1000).toLocaleDateString(undefined, { weekday: 'short' }),
      price: candle.close,
    })) ?? []
  }, [chartMarket])

  const filteredMarkets = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    const nextMarkets = markets.filter((market) => {
      if (!normalizedQuery) return true
      return [market.assetName, market.tokenName, market.ticker, market.country, market.streetAddress]
        .some((value) => value.toLowerCase().includes(normalizedQuery))
    })

    return [...nextMarkets].sort((a, b) => {
      if (sortBy === 'apr') return b.rentalYieldPercentage - a.rentalYieldPercentage
      if (sortBy === 'price-high') return b.marketPrice - a.marketPrice
      if (sortBy === 'price-low') return a.marketPrice - b.marketPrice
      return b.volume24h - a.volume24h
    })
  }, [markets, query, sortBy])

  const statItems = [
    { label: 'Live TVL', value: `$${tvl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, detail: 'Aggregated market value' },
    { label: 'Total Markets', value: `${totalMarkets}`, detail: 'Tradeable properties' },
    { label: 'Market Countries', value: `${supportedChains}`, detail: 'Geographic coverage' },
    { label: 'Average APR', value: `${apr.toFixed(2)}%`, detail: 'Based on rental yields' },
  ]

  return (
    <div className="app-shell">
      <Header />

      <main className="page-content">
        <section className="hero-panel" id="overview">
          <div>
            <div className="eyebrow">
              <Sparkles size={16} /> Live developer dashboard
            </div>
            <h1>Community-built, unofficial toolkit for Loaf Markets.</h1>
            <p className="hero-copy">
              Monitor live property markets, TVL, APR and geographic coverage with automatic refresh every 30 seconds.
            </p>
            <div className="hero-actions">
              {docsLinks.map((link) => (
                <a key={link.href} href={link.href} target="_blank" rel="noreferrer">
                  {link.label}
                  <ChevronRight size={16} />
                </a>
              ))}
            </div>
          </div>
          <div className="hero-meta">
            <div className="meta-card">
              <p>Live market snapshot</p>
              <strong>{loading ? 'Refreshing market data' : 'Connected to Loaf API'}</strong>
            </div>
          </div>
        </section>

        {error && <ErrorBanner message={error} />}

        <section className="stat-grid" aria-label="Dashboard statistics">
          {statItems.map((stat) => (
            <StatCard key={stat.label} label={stat.label} value={stat.value} detail={stat.detail} />
          ))}
        </section>

        <section className="chart-panel" id="markets">
          <div className="panel-heading">
            <div>
              <p>7-day live activity</p>
              <h2>{chartMarket ? `${chartMarket.assetName} performance` : 'Market performance'}</h2>
            </div>
            <button type="button" className="secondary-button refresh-button" onClick={refetch} disabled={loading}>
              <RefreshCw size={16} className={loading ? 'spin' : ''} />
              {loading ? 'Refreshing' : 'Refresh data'}
            </button>
          </div>

          {loading && markets.length === 0 ? (
            <Loading />
          ) : (
            <div className="chart-wrapper">
              <ResponsiveContainer width="100%" height={320}>
                <AreaChart data={chartData} margin={{ top: 10, right: 24, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ffd884" stopOpacity={0.78} />
                      <stop offset="95%" stopColor="#ffd884" stopOpacity={0.08} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tickLine={false} axisLine={false} stroke="#d5c182" />
                  <YAxis tickLine={false} axisLine={false} stroke="#d5c182" />
                  <CartesianGrid stroke="#3f3a2d" vertical={false} opacity={0.32} />
                  <Tooltip contentStyle={{ background: '#181814', border: '1px solid #3f3a2d', color: '#f4e3b4' }} cursor={{ stroke: '#5a4c2a', strokeDasharray: '3 3' }} />
                  <Area type="monotone" dataKey="price" stroke="#f1c65b" fill="url(#areaGradient)" strokeWidth={3} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="market-panel">
          <div className="panel-heading market-heading">
            <div>
              <p>Market explorer</p>
              <h2>Search and compare live properties</h2>
            </div>
            <span className="result-count">{filteredMarkets.length} results</span>
          </div>

          <div className="market-toolbar">
            <label className="search-field">
              <Search size={18} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search property, ticker, country or address"
                aria-label="Search markets"
              />
            </label>
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value as SortOption)} aria-label="Sort markets">
              <option value="volume">Highest 24h volume</option>
              <option value="apr">Highest rental yield</option>
              <option value="price-high">Highest price</option>
              <option value="price-low">Lowest price</option>
            </select>
          </div>

          <div className="market-grid">
            {loading && markets.length === 0 ? (
              Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="market-card skeleton-card">
                  <div className="loading-line short" />
                  <div className="loading-line" />
                  <div className="loading-line" />
                </div>
              ))
            ) : filteredMarkets.length > 0 ? (
              filteredMarkets.slice(0, 8).map((market) => <MarketCard key={market.propertyId} market={market} />)
            ) : (
              <div className="empty-state">
                <Search size={28} />
                <h3>No markets found</h3>
                <p>Try another property name, ticker, country or address.</p>
                <button type="button" className="secondary-button" onClick={() => setQuery('')}>Clear search</button>
              </div>
            )}
          </div>
        </section>

        <section className="orderbook-panel" id="orderbook">
          <div className="panel-heading">
            <div>
              <p>Order Book</p>
              <h2>Sample bid / ask levels</h2>
            </div>
          </div>

          <div className="orderbook-grid">
            {['Bids', 'Asks'].map((side) => (
              <div key={side}>
                <div className="orderbook-heading">{side}</div>
                <div className="order-table">
                  <div className="order-row order-row-header"><span>Price</span><span>Size</span><span>Total</span></div>
                  {chartMarket && [1, 2, 3, 4].map((level) => {
                    const isBid = side === 'Bids'
                    const price = chartMarket.marketPrice + (isBid ? -level * 0.45 : level * 0.55)
                    const size = Number((isBid ? 12 - level * 1.5 : 8 + level * 1.2).toFixed(2))
                    return (
                      <div key={level} className={`order-row ${isBid ? 'bid-row' : 'ask-row'}`}>
                        <span>${price.toFixed(2)}</span><span>{size}</span><span>{(price * size).toFixed(2)}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="resources-panel" id="resources">
          <div className="panel-heading"><div><p>Resources</p><h2>Official Loaf Markets docs</h2></div></div>
          <div className="resources-grid">
            {docsLinks.map((link) => (
              <a key={link.href} href={link.href} target="_blank" rel="noreferrer" className="resource-card">
                <span>{link.label}</span><ChevronRight size={18} />
              </a>
            ))}
          </div>
          <div className="security-note">
            <p>Security notice: this interface never asks for private keys. Authenticated trading calls should not be made directly from the browser.</p>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default App
