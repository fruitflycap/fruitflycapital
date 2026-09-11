const LOCAL_BRAIN_URL = 'ws://127.0.0.1:8765'
const DEPLOYED_BRAIN_URL = 'wss://29f7-2a12-26c0-510a-2a00-a8d9-25f1-ccca-bced.ngrok-free.app'
const RETIRED_RENDER_BRAIN_HOST = 'fruitflycapital.onrender.com'

/**
 * Keep local development pointed at the local adapter, but let a deployed
 * build reach the locally hosted brain through the ngrok websocket. A stale
 * Render value is intentionally ignored so an old Vercel env setting cannot
 * silently send the public app to the retired brain server. The endpoint
 * contains no credentials.
 */
export function resolveBrainWebSocketUrl(configured: string | undefined) {
  const explicit = configured?.trim()
  const host = window.location.hostname
  const isLocal = host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
  if (explicit && !explicit.includes(RETIRED_RENDER_BRAIN_HOST)) return explicit
  return isLocal ? LOCAL_BRAIN_URL : DEPLOYED_BRAIN_URL
}
