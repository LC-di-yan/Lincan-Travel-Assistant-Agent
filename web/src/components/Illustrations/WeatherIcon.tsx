function getWeatherType(text: string | undefined): string {
  if (!text) return 'cloudy'
  if (text.includes('晴') || text.includes('sunny')) return 'sunny'
  if (text.includes('雨') || text.includes('rain')) return 'rainy'
  if (text.includes('雪') || text.includes('snow')) return 'snowy'
  if (text.includes('云') || text.includes('阴') || text.includes('cloud')) return 'cloudy'
  if (text.includes('风') || text.includes('wind')) return 'cloudy'
  if (text.includes('雾') || text.includes('fog') || text.includes('霾')) return 'cloudy'
  return 'cloudy'
}

const WEATHER_LABELS: Record<string, string> = {
  sunny: '晴天',
  cloudy: '多云',
  rainy: '雨天',
  snowy: '雪天',
}

export function WeatherIcon({ text, size = 48, className = '' }: { text?: string; size?: number; className?: string }) {
  const type = getWeatherType(text)
  return (
    <img
      src={`/images/scenes/${type}.svg`}
      alt={WEATHER_LABELS[type] || '天气'}
      width={size}
      height={size}
      className={className}
      loading="lazy"
    />
  )
}
