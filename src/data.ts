export interface NavItem {
  label: string
  href: string
}

export interface StatCard {
  title: string
  value: string
  detail: string
}

export interface MarketRow {
  market: string
  symbol: string
  price: string
  change: string
  status: string
}

export interface OrderRow {
  price: string
  size: string
  total: string
  side: 'bid' | 'ask'
}

export const navItems: NavItem[] = [
  { label: 'Overview', href: '#overview' },
  { label: 'Markets', href: '#markets' },
  { label: 'Order Book', href: '#orderbook' },
  { label: 'Resources', href: '#resources' },
]

export const stats: StatCard[] = [
  { title: 'API Mode', value: 'Demo / Read-only', detail: 'Sample endpoint data' },
  { title: 'Demo Markets', value: '5 live simulations', detail: 'Fictional market depth' },
  { title: 'Network', value: 'Loaf Markets Testnet', detail: 'Community demo environment' },
  { title: 'Last Update', value: 'Just now', detail: 'Demo activity refreshed' },
]

export const areaChartData = [
  { date: 'Mon', activity: 180 },
  { date: 'Tue', activity: 210 },
  { date: 'Wed', activity: 175 },
  { date: 'Thu', activity: 240 },
  { date: 'Fri', activity: 220 },
  { date: 'Sat', activity: 260 },
  { date: 'Sun', activity: 230 },
]

export const marketRows: MarketRow[] = [
  {
    market: 'Golden Loaf / USD',
    symbol: 'GLF',
    price: '$0.84',
    change: '+4.8%',
    status: 'Active',
  },
  {
    market: 'Sourdough / USD',
    symbol: 'SDG',
    price: '$1.12',
    change: '-1.3%',
    status: 'Active',
  },
  {
    market: 'Crust Token / USD',
    symbol: 'CRST',
    price: '$0.42',
    change: '+0.9%',
    status: 'Paused',
  },
  {
    market: 'Baker Bond / USD',
    symbol: 'BND',
    price: '$3.05',
    change: '+2.4%',
    status: 'Active',
  },
  {
    market: 'Harvest Pair / USD',
    symbol: 'HVT',
    price: '$0.63',
    change: '-0.6%',
    status: 'Active',
  },
]

export const orderBookBids: OrderRow[] = [
  { price: '$0.84', size: '4.25', total: '4.25', side: 'bid' },
  { price: '$0.83', size: '7.10', total: '11.35', side: 'bid' },
  { price: '$0.82', size: '5.90', total: '17.25', side: 'bid' },
  { price: '$0.81', size: '3.40', total: '20.65', side: 'bid' },
]

export const orderBookAsks: OrderRow[] = [
  { price: '$0.85', size: '3.10', total: '3.10', side: 'ask' },
  { price: '$0.86', size: '2.80', total: '5.90', side: 'ask' },
  { price: '$0.87', size: '6.20', total: '12.10', side: 'ask' },
  { price: '$0.88', size: '3.50', total: '15.60', side: 'ask' },
]

export const docsLinks = [
  {
    label: 'Official Documentation',
    href: 'https://docs.loafmarkets.com/en/',
  },
  {
    label: 'API Reference',
    href: 'https://docs.loafmarkets.com/en/api-reference/',
  },
  {
    label: 'Trading Bot Guide',
    href: 'https://docs.loafmarkets.com/en/guides/building-a-trading-bot/',
  },
]
