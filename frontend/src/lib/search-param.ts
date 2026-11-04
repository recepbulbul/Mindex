import { useSearchParams } from 'react-router'

/**
 * A tab or filter kept in the URL (`?view=memory`), so it survives reloads and can be linked.
 * Unknown values fall back; choosing the fallback removes the parameter to keep URLs clean.
 */
export function useSearchParam<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(key)
  const value = allowed.find((v) => v === raw) ?? fallback

  const set = (next: T) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        if (next === fallback) p.delete(key)
        else p.set(key, next)
        return p
      },
      { replace: true },
    )

  return [value, set]
}
