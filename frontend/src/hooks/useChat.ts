import { useCallback, useState } from 'react'
import { useToast } from '../context/ToastContext'
import { ApiError, apiClient } from '../services/apiClient'
import type { ChatMessage } from '../types'

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError({ code: 'INTERNAL_ERROR', message: 'Something went wrong.', status: 0 })
}

export function useChat() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const { showApiError } = useToast()

  // FR-S01: switching to a past session replaces the local turn list with
  // the persisted history (Section 10.5) - HistoryTurn carries no message
  // id, so one is minted client-side same as for the optimistic user
  // message below.
  const loadSession = useCallback(
    async (targetSessionId: string) => {
      if (isLoading || isHistoryLoading) return
      setIsHistoryLoading(true)
      try {
        const response = await apiClient.getHistory(targetSessionId)
        setSessionId(response.session_id)
        setMessages(
          response.turns.map((turn) => ({
            id: crypto.randomUUID(),
            role: turn.role,
            content: turn.content,
            citations: turn.citations,
            confidence: turn.confidence,
            notFound: turn.confidence === 'not_found',
            createdAt: turn.created_at,
          })),
        )
      } catch (err) {
        showApiError(toApiError(err))
      } finally {
        setIsHistoryLoading(false)
      }
    },
    [isLoading, isHistoryLoading, showApiError],
  )

  // FR-S01: a session is created implicitly on first message - "starting a
  // new conversation" client-side is just clearing local state so the next
  // sendMessage sends session_id: null.
  const startNewSession = useCallback(() => {
    setSessionId(null)
    setMessages([])
  }, [])

  const sendMessage = useCallback(
    async (question: string) => {
      if (isLoading) return

      const userMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        content: question,
        citations: [],
        confidence: null,
        notFound: false,
        createdAt: new Date().toISOString(),
      }
      setMessages((current) => [...current, userMessage])
      setIsLoading(true)

      try {
        const response = await apiClient.chat({ session_id: sessionId, question })
        setSessionId(response.session_id)
        setMessages((current) => [
          ...current,
          {
            id: response.message_id,
            role: 'assistant',
            content: response.answer,
            citations: response.citations,
            confidence: response.confidence,
            notFound: response.not_found,
            createdAt: new Date().toISOString(),
          },
        ])
      } catch (err) {
        showApiError(toApiError(err))
      } finally {
        setIsLoading(false)
      }
    },
    [isLoading, sessionId, showApiError],
  )

  return {
    sessionId,
    messages,
    isLoading,
    isHistoryLoading,
    sendMessage,
    loadSession,
    startNewSession,
  }
}
