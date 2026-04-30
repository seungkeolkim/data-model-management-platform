/**
 * 클립보드 복사 — secure context (HTTPS / localhost) 가 아니면 navigator.clipboard 가
 * undefined 가 되어 `Cannot read properties of undefined` 에러가 난다. HTTP + 사설 IP 등
 * 환경에서도 동작하도록 textarea + execCommand fallback 사용.
 */
export function copyToClipboard(text: string): boolean {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      navigator.clipboard.writeText(text)
      return true
    } catch {
      // secure context 가 아니면 여기로 — fallback 시도
    }
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
    return true
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
  }
}
