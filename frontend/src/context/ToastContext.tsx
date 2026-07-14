// Central error/notice surface (SDD Section 9: "context/ - session/toast
// providers"). Every ApiError in the app should end up here via
// showApiError() rather than a bespoke inline banner, so every Section
// 10.8 code gets one consistent, dismissible presentation - including a
// live Retry-After countdown for 429/LLM_QUOTA_EXCEEDED instead of a
// static "please wait a moment" with no indication of how long.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { ApiError } from '../services/apiClient'

type ToastVariant = 'error' | 'info'

interface ToastItem {
  id: string
  message: string
  variant: ToastVariant
  retryAfterSeconds?: number
  createdAtMs: number
}

interface ToastContextValue {
  showToast: (message: string, options?: { variant?: ToastVariant; retryAfterSeconds?: number }) => void
  showApiError: (error: ApiError) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_DISMISS_MS = 6000

function CountdownSuffix({ retryAfterSeconds, createdAtMs }: { retryAfterSeconds: number; createdAtMs: number }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [])

  const remaining = Math.max(0, Math.ceil(retryAfterSeconds - (now - createdAtMs) / 1000))
  if (remaining === 0) return null
  return <span className="ml-1 font-medium">Try again in {remaining}s</span>
}

function ToastRow({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: string) => void }) {
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg ${
        toast.variant === 'error'
          ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950 dark:text-red-300'
          : 'border-gray-200 bg-white text-gray-700 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-200'
      }`}
    >
      <span className="min-w-0 flex-1">
        {toast.message}
        {toast.retryAfterSeconds !== undefined && (
          <CountdownSuffix retryAfterSeconds={toast.retryAfterSeconds} createdAtMs={toast.createdAtMs} />
        )}
      </span>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss"
        className="shrink-0 text-base leading-none opacity-60 hover:opacity-100"
      >
        ×
      </button>
    </div>
  )
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>())

  const dismissToast = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const showToast = useCallback(
    (message: string, options?: { variant?: ToastVariant; retryAfterSeconds?: number }) => {
      const id = crypto.randomUUID()
      const toast: ToastItem = {
        id,
        message,
        variant: options?.variant ?? 'error',
        retryAfterSeconds: options?.retryAfterSeconds,
        createdAtMs: Date.now(),
      }
      setToasts((current) => [...current, toast])

      const lifetimeMs =
        options?.retryAfterSeconds !== undefined
          ? (options.retryAfterSeconds + 3) * 1000
          : DEFAULT_DISMISS_MS
      const timer = setTimeout(() => {
        setToasts((current) => current.filter((item) => item.id !== id))
        timersRef.current.delete(id)
      }, lifetimeMs)
      timersRef.current.set(id, timer)
    },
    [],
  )

  const showApiError = useCallback(
    (error: ApiError) => {
      showToast(error.friendlyMessage, { variant: 'error', retryAfterSeconds: error.retryAfterSeconds })
    },
    [showToast],
  )

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      for (const timer of timers.values()) clearTimeout(timer)
    }
  }, [])

  return (
    <ToastContext.Provider value={{ showToast, showApiError }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto w-full max-w-sm">
            <ToastRow toast={toast} onDismiss={dismissToast} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
