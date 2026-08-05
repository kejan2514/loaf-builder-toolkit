import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChevronRight, Sparkles } from 'lucide-react'
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

function App() {
  const { markets, loading, error, totalMarkets, supportedChains, tvl, apr } = useMarkets(30000)
  const chartMarket = markets[0]

  const chartData = useMemo(() => {
    return chartMarket?.candlesticks.slice(-7).map((candle) => ({
      date: new Date(candle.time * 1000).toLocaleDateString(undefined, { weekday: 'short' }),
      price: candle.close,
    })) ?? []
  }, [chartMarket])

  const statItems = [
    { label: 'Live TVL', value: `$${tvl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, detail: 'Aggregated market value' },
    { label: 'Total Markets', value: `${totalMarkets}`, detail: 'Tradeable properties' },
    { label: 'Supported Chains', value: `${supportedChains}`, detail: 'Country market coverage' },
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
              Monitor live property markets, TVL, APR and chain coverage with refresh every 30 seconds. This dashboard pulls data from the official Loaf Markets API.
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
              <strong>{loading ? 'Refreshing every 30 seconds' : 'Connected to Loaf API'}</strong>
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
            <button type="button" className="secondary-button" onClick={() => window.location.reload()}>
              Refresh now
            </button>
          </div>

          {loading ? (
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
          <div className="panel-heading">
            <div>
              <p>Market cards</p>
              <h2>Live property listings</h2>
            </div>
          </div>

          <div className="market-grid">
            {loading ? (
              Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="market-card skeleton-card">
                  <div className="loading-line short" />
                  <div className="loading-line" />
                  <div className="loading-line" />
                </div>
              ))
            ) : (
              markets.slice(0, 4).map((market) => <MarketCard key={market.propertyId} market={market} />)
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
            <div>
              <div className="orderbook-heading">Bids</div>
              <div className="order-table">
                <div className="order-row order-row-header">
                  <span>Price</span>
                  <span>Size</span>
                  <span>Total</span>
                </div>
                {chartMarket ? (
                  [1, 2, 3, 4].map((level) => {
                    const price = chartMarket.marketPrice - level * 0.45
                    const size = Number((12 - level * 1.5).toFixed(2))
                    return (
                      <div key={level} className="order-row bid-row">
                        <span>${price.toFixed(2)}</span>
                        <span>{size}</span>
                        <span>{(price * size).toFixed(2)}</span>
                      </div>
                    )
                  })
                ) : (
                  Array.from({ length: 4 }).map((_, index) => (
                    <div key={index} className="order-row bid-row skeleton-row">
                      <span className="loading-line tiny" />
                      <span className="loading-line tiny" />
                      <span className="loading-line tiny" />
                    </div>
                  ))
                )}
              </div>
            </div>

            <div>
              <div className="orderbook-heading">Asks</div>
              <div className="order-table">
                <div className="order-row order-row-header">
                  <span>Price</span>
                  <span>Size</span>
                  <span>Total</span>
                </div>
                {chartMarket ? (
                  [1, 2, 3, 4].map((level) => {
                    const price = chartMarket.marketPrice + level * 0.55
                    const size = Number((8 + level * 1.2).toFixed(2))
                    return (
                      <div key={level} className="order-row ask-row">
                        <span>${price.toFixed(2)}</span>
                        <span>{size}</span>
                        <span>{(price * size).toFixed(2)}</span>
                      </div>
                    )
                  })
                ) : (
                  Array.from({ length: 4 }).map((_, index) => (
                    <div key={index} className="order-row ask-row skeleton-row">
                      <span className="loading-line tiny" />
                      <span className="loading-line tiny" />
                      <span className="loading-line tiny" />
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </section>

        <section className="resources-panel" id="resources">
          <div className="panel-heading">
            <div>
              <p>Resources</p>
              <h2>Official Loaf Markets docs</h2>
            </div>
          </div>
          <div className="resources-grid">
            {docsLinks.map((link) => (
              <a key={link.href} href={link.href} target="_blank" rel="noreferrer" className="resource-card">
                <span>{link.label}</span>
                <ChevronRight size={18} />
              </a>
            ))}
          </div>
          <div className="security-note">
            <p>
              Security notice: this interface never asks for private keys. Authenticated trading calls should not be made directly from the browser.
            </p>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default App
