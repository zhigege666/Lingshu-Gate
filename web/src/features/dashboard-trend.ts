/** Zero-based geometry; line segments never invent intermediate extrema. */
export function trendGeometry(values: readonly number[]) {
  const safe = values.map(value => Number.isFinite(value) ? Math.max(0, value) : 0)
  const max = Math.max(1, ...safe)
  const magnitude = 10 ** Math.floor(Math.log10(max / 4))
  const step = Math.max(1, ([1, 2, 5, 10].find(value => value * magnitude >= max / 4) || 10) * magnitude)
  const ceiling = step * 4
  const points = safe.map((value, index) => ({ x: safe.length === 1 ? 50 : index / Math.max(1, safe.length - 1) * 100, y: (1 - value / ceiling) * 100 }))
  const line = points.map((point, index) => `${index ? "L" : "M"}${point.x * 7.2},${point.y * 1.6}`).join(" ")
  const area = points.length ? `${line} L${points.at(-1)!.x * 7.2},160 L${points[0].x * 7.2},160 Z` : ""
  return { points, line, area, ticks: [ceiling, ceiling * .75, ceiling * .5, ceiling * .25, 0] }
}

export function trendPointerIndex(relativeX: number, width: number, count: number) {
  if (count <= 1 || width <= 0) return 0
  return Math.max(0, Math.min(count - 1, Math.round(relativeX / width * (count - 1))))
}
