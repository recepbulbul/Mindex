/**
 * True when the MSW mock API answers instead of the backend (`npm run dev`, GitHub Pages).
 * Written as the bare comparison so Vite inlines it as a build-time constant: in a real-API
 * build the mock-only branches (demo accounts, "sahte API" notes) are dropped as dead code.
 */
export const USING_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

/** Where the numbers come from, for the "no real money" notes across the UI. */
export function dataNote(mocks: boolean): string {
  return mocks ? 'tüm veriler sahte' : 'geçmiş fiyat verisiyle yeniden oynatma'
}

export const DATA_NOTE = dataNote(USING_MOCKS)
