export function clsx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

export function formatTime(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatPercent(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value?: number | null, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return value.toFixed(digits)
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function toLabelList(input: string): string[] {
  return input
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function wsBaseUrl(httpBase: string): string {
  if (httpBase.startsWith('https://')) return `wss://${httpBase.slice(8)}`
  if (httpBase.startsWith('http://')) return `ws://${httpBase.slice(7)}`
  return httpBase
}
