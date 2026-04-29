/**
 * Chat UIs render plain text only (no markdown). Strips **bold** only (keeps __dunders__).
 */
export function stripLightMarkdown(text) {
  if (text == null || text === '') return ''
  let s = String(text)
  for (let n = 0; n < 16; n++) {
    const next = s.replace(/\*\*([^*]+)\*\*/g, '$1')
    if (next === s) break
    s = next
  }
  return s
}
