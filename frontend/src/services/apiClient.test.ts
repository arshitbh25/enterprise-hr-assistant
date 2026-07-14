import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiClient } from './apiClient'

function jsonResponse(
  body: unknown,
  init: { status: number; headers?: Record<string, string> },
): Response {
  return new Response(JSON.stringify(body), {
    status: init.status,
    headers: { 'content-type': 'application/json', ...init.headers },
  })
}

describe('apiClient error mapping', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    fetchMock.mockReset()
    vi.unstubAllGlobals()
  })

  it('parses the structured error envelope into an ApiError', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'INVALID_QUESTION',
            message: 'Question is required.',
            details: { field: 'question' },
          },
          request_id: 'r1',
        },
        { status: 422 },
      ),
    )

    const error = await apiClient.chat({ session_id: null, question: '' }).catch((err) => err)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('INVALID_QUESTION')
    expect(error.message).toBe('Question is required.')
    expect(error.status).toBe(422)
    expect(error.details).toEqual({ field: 'question' })
  })

  it('extracts the Retry-After header into retryAfterSeconds', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: 'RATE_LIMITED', message: 'Slow down.' }, request_id: 'r2' },
        { status: 429, headers: { 'Retry-After': '5' } },
      ),
    )

    const error = await apiClient
      .chat({ session_id: null, question: 'How many leaves?' })
      .catch((err) => err)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('RATE_LIMITED')
    expect(error.retryAfterSeconds).toBe(5)
  })

  it('uploadDocuments returns the body on a non-2xx response when it carries per-file results', async () => {
    // Section 10.1: a duplicate-only batch is still a 409 with a per-file
    // results array, not a hard failure - apiClient must surface that body
    // instead of throwing, via the acceptBody escape hatch on request().
    const body = {
      results: [
        {
          file_name: 'a.pdf',
          document_id: null,
          status: 'REJECTED',
          error: { code: 'DUPLICATE_DOCUMENT', message: 'Already uploaded.' },
        },
      ],
      request_id: 'r3',
    }
    fetchMock.mockResolvedValue(jsonResponse(body, { status: 409 }))

    const file = new File(['%PDF-1.4'], 'a.pdf', { type: 'application/pdf' })
    const response = await apiClient.uploadDocuments([file])

    expect(response).toEqual(body)
  })
})
