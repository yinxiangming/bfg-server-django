/**
 * Example API helper for the OpenAI analyze endpoint (optional).
 */
export async function postAiAnalyze(text: string): Promise<unknown> {
  const base = process.env.NEXT_PUBLIC_API_URL?.trim()
  if (!base) {
    throw new Error('NEXT_PUBLIC_API_URL is not set')
  }
  const url = `${base.replace(/\/+$/, '')}/api/v1/__APP_SLUG__/ai/analyze/`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}
