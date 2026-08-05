import type { NavItem } from '../types'

const navItems: NavItem[] = [
  { label: 'Overview', href: '#overview' },
  { label: 'Markets', href: '#markets' },
  { label: 'Order Book', href: '#orderbook' },
  { label: 'Resources', href: '#resources' },
]

export function Header() {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">🥖</span>
        <div>
          <p>Loaf Builder Toolkit</p>
          <small>Community-built developer dashboard</small>
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
  )
}
