/** True when the MSW mock API answers instead of the backend (`npm run dev`, GitHub Pages). */
export const USING_MOCKS = usingMocks(import.meta.env.VITE_USE_MOCKS)

/** Where the numbers come from, for the "no real money" notes across the UI. */
export const DATA_NOTE = dataNote(USING_MOCKS)

// Pure helpers, so both modes are testable whatever the build's flag is.
export function usingMocks(flag: string | undefined): boolean {
  return flag === 'true'
}

export function dataNote(mocks: boolean): string {
  return mocks ? 'tüm veriler sahte' : 'geçmiş fiyat verisiyle yeniden oynatma'
}
