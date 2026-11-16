import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { documentEventsUrl, errorMessage, resolveApiBase } from './client'

function axiosError(status: number, data: unknown) {
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', undefined, undefined, {
    status, statusText: '', data, headers: {}, config: { headers: new AxiosHeaders() },
  })
}

describe('errorMessage', () => {
  it('prefers the FastAPI detail string', () => {
    expect(errorMessage(axiosError(400, { detail: "That file isn't a valid PDF." })))
      .toBe("That file isn't a valid PDF.")
  })
  it('explains size and rate limits', () => {
    expect(errorMessage(axiosError(413, '<html>'))).toBe('That PDF is too large.')
    expect(errorMessage(axiosError(429, {}))).toMatch(/Rate limit/)
  })
  it('handles plain errors', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage('weird', 'fallback')).toBe('fallback')
  })
})

describe('documentEventsUrl', () => {
  it('builds the SSE endpoint under the API base', () => {
    expect(documentEventsUrl('abc')).toBe('/api/documents/abc/events')
  })
})

describe('resolveApiBase', () => {
  it('defaults to the same-origin proxy', () => {
    expect(resolveApiBase(undefined)).toBe('/api')
    expect(resolveApiBase('  ')).toBe('/api')
  })
  it('accepts full URLs and bare hosts', () => {
    expect(resolveApiBase('https://api.example.com/')).toBe('https://api.example.com')
    expect(resolveApiBase('synapse-api.onrender.com')).toBe('https://synapse-api.onrender.com')
  })
})
