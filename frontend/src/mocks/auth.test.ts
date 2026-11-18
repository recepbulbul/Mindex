import { describe, expect, it } from 'vitest'
import { api, ApiError, tokenStore } from '@/api/client'
import type { LoginResponse, RegisterRequest, User } from '@/api/types'

const register = (body: RegisterRequest) => api.post<LoginResponse>('/auth/register', body)

describe('mock auth contract', () => {
  it('registers a viewer, who can then log in and read /auth/me', async () => {
    const res = await register({ email: 'Yeni@Mindex.dev', password: 'yeni-parola-1' })
    expect(res.user).toEqual<User>({ email: 'yeni@mindex.dev', role: 'viewer' })

    const login = await api.post<LoginResponse>('/auth/login', {
      email: 'yeni@mindex.dev',
      password: 'yeni-parola-1',
    })
    tokenStore.set(login.token)
    await expect(api.get<User>('/auth/me')).resolves.toEqual(res.user)
  })

  it('answers 409 with a field error when the e-mail is taken', async () => {
    const err = await register({ email: 'arastirmaci@mindex.dev', password: 'baska-parola' }).catch(
      (e: unknown) => e,
    )
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 409, fields: { email: expect.any(String) as string } })
  })

  it('rejects an old-format token on /auth/me', async () => {
    tokenStore.set(`mock.researcher.${crypto.randomUUID()}`)
    await expect(api.get('/auth/me')).rejects.toMatchObject({ status: 401 })
  })

  it('returns the demo researcher from /auth/me and needs a token', async () => {
    await expect(api.get('/auth/me')).rejects.toMatchObject({ status: 401 })
    const login = await api.post<LoginResponse>('/auth/login', {
      email: 'arastirmaci@mindex.dev',
      password: 'mindex-demo',
    })
    tokenStore.set(login.token)
    await expect(api.get<User>('/auth/me')).resolves.toEqual({
      email: 'arastirmaci@mindex.dev',
      role: 'researcher',
    })
  })
})
