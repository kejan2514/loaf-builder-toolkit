export interface Candlestick {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface LiquidityInfo {
  status: string
  reason: string
  healthy: boolean
}

export interface PropertyMarket {
  propertyId: number
  tokenName: string
  assetName: string
  ticker: string
  contractAddress: string
  streetAddress: string
  country: string
  latitude: number
  longitude: number
  propertyType: string
  status: string
  totalTokens: number
  headerImageUrl: string
  videoUrl: string
  marketPrice: number
  dailyReferencePrice: number
  volume24h: number
  rentalYieldPercentage: number
  candlesticks: Candlestick[]
  liquidity: LiquidityInfo
  isCompetition: boolean
}

export interface TradeResponse {
  properties: PropertyMarket[]
}

export interface NavItem {
  label: string
  href: string
}

export interface DocLink {
  label: string
  href: string
}
