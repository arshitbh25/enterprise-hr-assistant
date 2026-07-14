import { useCallback, useEffect, useRef, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { ApiError, apiClient } from '../services/apiClient'
import { NON_TERMINAL_DOCUMENT_STATUSES } from '../types'
import type { DocumentDeleteResponse, DocumentSummary, UploadFileResult } from '../types'

const POLL_INTERVAL_MS = 3000

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError({ code: 'INTERNAL_ERROR', message: 'Something went wrong.', status: 0 })
}

function hasNonTerminal(items: DocumentSummary[]): boolean {
  return items.some((doc) => NON_TERMINAL_DOCUMENT_STATUSES.includes(doc.status))
}

export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const { showApiError } = useToast()

  const mountedRef = useRef(true)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // `silent` skips the toast for background refreshes (poll ticks,
  // post-mutation re-fetches) where a transient failure isn't worth
  // interrupting the user - only the initial load and direct user actions
  // (upload/delete) surface a toast.
  const refresh = useCallback(
    async (options?: { silent?: boolean }): Promise<DocumentSummary[]> => {
      try {
        const response = await apiClient.listDocuments({ page_size: 100 })
        if (mountedRef.current) setDocuments(response.items)
        return response.items
      } catch (err) {
        if (!options?.silent) showApiError(toApiError(err))
        return []
      }
    },
    [showApiError],
  )

  // Self-scheduling poll: only re-arms itself while some document is still
  // mid-ingestion, based on the freshly-fetched items (not stale state) -
  // stops naturally once everything reaches READY/FAILED.
  const scheduleTick = useCallback(() => {
    stopPolling()
    timerRef.current = setTimeout(async () => {
      const items = await refresh({ silent: true })
      if (mountedRef.current && hasNonTerminal(items)) {
        scheduleTick()
      }
    }, POLL_INTERVAL_MS)
  }, [refresh, stopPolling])

  useEffect(() => {
    mountedRef.current = true
    setIsLoading(true)
    refresh().then((items) => {
      if (!mountedRef.current) return
      setIsLoading(false)
      if (hasNonTerminal(items)) scheduleTick()
    })
    return () => {
      mountedRef.current = false
      stopPolling()
    }
  }, [refresh, scheduleTick, stopPolling])

  const uploadFiles = useCallback(
    async (files: File[]): Promise<UploadFileResult[]> => {
      setIsUploading(true)
      try {
        const response = await apiClient.uploadDocuments(files)
        const items = await refresh({ silent: true })
        if (hasNonTerminal(items)) scheduleTick()
        return response.results
      } catch (err) {
        showApiError(toApiError(err))
        return []
      } finally {
        if (mountedRef.current) setIsUploading(false)
      }
    },
    [refresh, scheduleTick, showApiError],
  )

  const deleteDocument = useCallback(
    async (documentId: string): Promise<DocumentDeleteResponse> => {
      try {
        const result = await apiClient.deleteDocument(documentId)
        await refresh({ silent: true })
        return result
      } catch (err) {
        throw toApiError(err)
      }
    },
    [refresh],
  )

  return { documents, isLoading, isUploading, uploadFiles, deleteDocument }
}
