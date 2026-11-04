import type { KeyboardEvent } from 'react'

/**
 * Arrow/Home/End navigation for a tablist or radiogroup made of buttons (WAI-ARIA APG):
 * moves focus to the neighbouring option and selects it. Options use roving tabIndex (0 / -1).
 */
export function rovingKeyDown(e: KeyboardEvent<HTMLElement>) {
  const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')]
  const i = items.indexOf(document.activeElement as HTMLButtonElement)
  if (i < 0) return

  let next: number
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = i + 1
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = i - 1
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = items.length - 1
  else return

  e.preventDefault()
  const target = items[(next + items.length) % items.length]!
  target.focus()
  target.click()
}
