/** True when the MSW mock API answers instead of the backend (`npm run dev`, GitHub Pages). */
export const USING_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

/** Where the numbers come from, for the "no real money" notes across the UI. */
export const DATA_NOTE = USING_MOCKS ? 'tüm veriler sahte' : 'geçmiş fiyat verisiyle replay'
