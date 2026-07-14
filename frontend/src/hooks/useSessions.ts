import { useCallback, useEffect, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { ApiError, apiClient } from '../services/apiClient'
import type { HistoryDeleteResponse, SessionSummary } from '../types'

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError({ code: 'INTERNAL_ERROR', message: 'Something went wrong.', status: 0 })
}

export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const { showApiError } = useToast()

  // `silent` skips the toast for background refreshes (e.g. ChatPage
  // re-fetching after every completed turn) - only the initial load and
  // direct user actions (delete) surface a toast.
  const refresh = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        const response = await apiClient.listSessions({ page_size: 50 })
        setSessions(response.items)
      } catch (err) {
        if (!options?.silent) showApiError(toApiError(err))
      }
    },
    [showApiError],
  )

  useEffect(() => {
    setIsLoading(true)
    refresh().finally(() => setIsLoading(false))
  }, [refresh])

  // FR-S04: deletes one session's turns (not just a client-side removal) -
  // the caller decides whether the deleted session was the active
  // conversation and needs to reset it.
  const deleteSession = useCallback(
    async (sessionId: string): Promise<HistoryDeleteResponse> => {
      try {
        const result = await apiClient.deleteHistory({ sessionId })
        await refresh({ silent: true })
        return result
      } catch (err) {
        throw toApiError(err)
      }
    },
    [refresh],
  )

  return { sessions, isLoading, refresh, deleteSession }
}
