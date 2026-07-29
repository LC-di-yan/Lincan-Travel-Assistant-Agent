const CITY_MAP: Record<string, string> = {
  '北京': '/images/cities/beijing.svg',
  '上海': '/images/cities/shanghai.svg',
  '广州': '/images/cities/guangzhou.svg',
  '深圳': '/images/cities/shenzhen.svg',
  '成都': '/images/cities/chengdu.svg',
  '杭州': '/images/cities/hangzhou.svg',
}

export function getCityImage(city: string | undefined): string {
  if (!city) return '/images/cities/default-city.svg'
  for (const [name, src] of Object.entries(CITY_MAP)) {
    if (city.includes(name)) return src
  }
  return '/images/cities/default-city.svg'
}

export function CityIllustration({ city, className = '' }: { city?: string; className?: string }) {
  return (
    <img
      src={getCityImage(city)}
      alt={city || '城市'}
      className={`pointer-events-none select-none ${className}`}
      loading="lazy"
    />
  )
}
