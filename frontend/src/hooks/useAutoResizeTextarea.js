import { useLayoutEffect, useRef } from 'react'

/**
 * Auto-grow textarea: min/max row bounds, internal scroll after max.
 */
export function useAutoResizeTextarea(value, { minRows = 2, maxRows = 12 } = {}) {
  const ref = useRef(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = '0px'
    const style = getComputedStyle(el)
    const lineHeight = parseFloat(style.lineHeight) || 21
    const padY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
    const minH = lineHeight * minRows + padY
    const maxH = lineHeight * maxRows + padY
    const contentH = el.scrollHeight
    const next = Math.min(Math.max(contentH, minH), maxH)
    el.style.height = `${next}px`
    el.style.overflowY = contentH > maxH ? 'auto' : 'hidden'
  }, [value, minRows, maxRows])

  return ref
}
