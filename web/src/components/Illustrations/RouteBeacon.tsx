/** Two folded wings with a central sight, shared by the brand and the active task. */
export function RouteBeacon({ size = 24 }: { size?: number }) {
  return <svg aria-hidden="true" viewBox="0 0 32 32" width={size} height={size} fill="currentColor">
    <path d="M3 26.5 12.9 7 16 2.7l2.1 8.9-5.6 10.6-9.5 4.3Z" />
    <path d="m19.3 10.5 9.9 16-11.1-4.6-1.8-5.3 3-6.1Z" opacity=".78" />
    <circle cx="15" cy="25" r="2" />
  </svg>
}
