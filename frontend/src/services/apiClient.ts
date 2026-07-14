// The ONLY module that knows URLs/HTTP (SDD Section 9). Every component
// goes through the typed methods below - never `fetch` directly - so
// base URL, error mapping, and Retry-After handling live in one place.

import { friendlyMessageFor } from './errorMessages'
import type {
  ChatRequest,
  ChatResponse,
  DocumentDeleteResponse,
  DocumentListResponse,
  DocumentStatus,
  ErrorEnvelope,
  HealthResponse,
  HistoryDeleteResponse,
  HistoryResponse,
  SessionListResponse,
  UploadResponse,
} from '../types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly retryAfterSeconds?: number
  readonly details?: Record<string, unknown>

  constructor(params: {
    code: string
    message: string
    status: number
    retryAfterSeconds?: number
    details?: Record<string, unknown>
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.code = params.code
    this.status = params.status
    this.retryAfterSeconds = params.retryAfterSeconds
    this.details = params.details
  }

  /** User-facing copy for this error (Section 10.8 catalogue -> friendly text). */
  get friendlyMessage(): string {
    return friendlyMessageFor(this.code, this.message)
  }
}

function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  return (
    typeof body === 'object' &&
    body !== null &&
    'error' in body &&
    typeof (body as { error?: unknown }).error === 'object'
  )
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { acceptBody?: (body: unknown) => boolean },
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, init)
  } catch {
    throw new ApiError({
      code: 'NETWORK_ERROR',
      message: 'Could not reach the server.',
      status: 0,
    })
  }

  const contentType = response.headers.get('content-type') ?? ''
  const body = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : null

  if (!response.ok) {
    if (options?.acceptBody?.(body)) {
      return body as T
    }

    const retryAfterHeader = response.headers.get('Retry-After')
    const retryAfterSeconds = retryAfterHeader ? Number(retryAfterHeader) : undefined

    if (isErrorEnvelope(body)) {
      throw new ApiError({
        code: body.error.code,
        message: body.error.message,
        status: response.status,
        details: body.error.details,
        retryAfterSeconds,
      })
    }

    throw new ApiError({
      code: 'HTTP_ERROR',
      message: response.statusText || 'Request failed.',
      status: response.status,
      retryAfterSeconds,
    })
  }

  return body as T
}

export const apiClient = {
  health: () => request<HealthResponse>('/health'),

  chat: (payload: ChatRequest) =>
    request<ChatResponse>('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  listDocuments: (
    params: { status?: DocumentStatus; page?: number; page_size?: number } = {},
  ) => request<DocumentListResponse>(`/documents${buildQuery(params)}`),

  uploadDocuments: (files: File[]) => {
    const formData = new FormData()
    for (const file of files) formData.append('files', file)
    // Section 10.1: the response body always carries per-file results, even
    // when the overall status is 4xx (e.g. every file was a duplicate) - that
    // status reflects the batch outcome, not a hard failure, so we surface
    // the body instead of throwing whenever it has the shape we expect.
    return request<UploadResponse>(
      '/upload',
      { method: 'POST', body: formData },
      { acceptBody: (body) => Array.isArray((body as UploadResponse | null)?.results) },
    )
  },

  deleteDocument: (documentId: string) =>
    request<DocumentDeleteResponse>(`/documents/${documentId}`, { method: 'DELETE' }),

  listSessions: (params: { page?: number; page_size?: number } = {}) =>
    request<SessionListResponse>(`/sessions${buildQuery(params)}`),

  getHistory: (sessionId: string, limit?: number) =>
    request<HistoryResponse>(`/history${buildQuery({ session_id: sessionId, limit })}`),

  deleteHistory: (params: { sessionId?: string; all?: boolean }) =>
    request<HistoryDeleteResponse>(
      `/history${buildQuery({ session_id: params.sessionId, all: params.all })}`,
      { method: 'DELETE' },
    ),
}
