import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { BookOpen, ChevronRight, Layers, Link, Sparkles } from 'lucide-react'
import {
  areaChartData,
  docsLinks,
  marketRows,
  navItems,
  orderBookAsks,
  orderBookBids,
  stats,
} from './data'

function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">🥖</span>
          <div>
            <p>Loaf Builder Toolkit</p>
            <small>Community-built dashboard</small>
          </div>
        </div>
        <nav className="nav-links" aria-label="Primary navigation">
          {navItems.map((item) => (
            <a key={item.href} href={item.href}>
              {item.label}
            </a>
          ))}
        </nav>
      </header>

      <main className="page-content">
        <section className="hero-panel" id="overview">
          <div>
            <div className="eyebrow">
              <Sparkles size={16} /> Demo Toolkit
            </div>
            <h1>Community-built, unofficial toolkit for Loaf Markets.</h1>
            <p className="hero-copy">
              Explore a warm, dark dashboard with sample market data, order book depth and official docs links. This interface is for demonstration only.
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
              <p>Demo market activity</p>
              <strong>Sample values only</strong>
            </div>
          </div>
        </section>

        <section className="stat-grid" aria-label="Dashboard statistics">
          {stats.map((stat) => (
            <article key={stat.title} className="stat-card">
              <p>{stat.title}</p>
              <strong>{stat.value}</strong>
              <span>{stat.detail}</span>
            </article>
          ))}
        </section>

        <section className="chart-panel">
          <div className="panel-heading">
            <div>
              <p>7-day demo activity</p>
              <h2>Market volume (demo data)</h2>
            </div>
            <button type="button" className="secondary-button">
              View API docs
            </button>
          </div>
          <div className="chart-wrapper">
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={areaChartData} margin={{ top: 10, right: 24, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ffd884" stopOpacity={0.8} />
                    <stop offset="95%" stopColor="#ffd884" stopOpacity={0.08} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tickLine={false} axisLine={false} stroke="#d5c182" />
                <YAxis tickLine={false} axisLine={false} stroke="#d5c182" />
                <CartesianGrid stroke="#3f3a2d" vertical={false} opacity={0.5} />
                <Tooltip contentStyle={{ background: '#181814', border: '1px solid #3f3a2d', color: '#f4e3b4' }} cursor={{ stroke: '#5a4c2a', strokeDasharray: '3 3' }} />
                <Area type="monotone" dataKey="activity" stroke="#f1c65b" fill="url(#areaGradient)" strokeWidth={3} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="market-panel" id="markets">
          <div className="panel-heading">
            <div>
              <p>Demo Markets</p>
              <h2>Fictional property markets</h2>
            </div>
            <button type="button" className="secondary-button">
              Download data
            </button>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Symbol</th>
                  <th>Price</th>
                  <th>24h</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {marketRows.map((row) => (
                  <tr key={row.market}>
                    <td>{row.market}</td>
                    <td>{row.symbol}</td>
                    <td>{row.price}</td>
                    <td>{row.change}</td>
                    <td>{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="orderbook-panel" id="orderbook">
          <div className="panel-heading">
            <div>
              <p>Order Book</p>
              <h2>Bid and ask depth</h2>
            </div>
            <button type="button" className="secondary-button">
              Switch view
            </button>
          </div>
          <div className="orderbook-grid">
            <div>
              <div className="subheading">
                <Layers size={18} /> Bids
              </div>
              <div className="order-table">
                <div className="order-row order-row-header">
                  <span>Price</span>
                  <span>Size</span>
                  <span>Total</span>
                </div>
                {orderBookBids.map((row) => (
                  <div key={row.price} className="order-row bid-row">
                    <span>{row.price}</span>
                    <span>{row.size}</span>
                    <span>{row.total}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="subheading">
                <BookOpen size={18} /> Asks
              </div>
              <div className="order-table">
                <div className="order-row order-row-header">
                  <span>Price</span>
                  <span>Size</span>
                  <span>Total</span>
                </div>
                {orderBookAsks.map((row) => (
                  <div key={row.price} className="order-row ask-row">
                    <span>{row.price}</span>
                    <span>{row.size}</span>
                    <span>{row.total}</span>
                  </div>
                ))}
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
                <div>
                  <Link size={18} />
                  <span>{link.label}</span>
                </div>
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

      <footer className="site-footer">
        <p>Community-built and not an official Loaf Markets product.</p>
      </footer>
    </div>
  )
}

export default App
