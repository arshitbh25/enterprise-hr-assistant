import { useState } from 'react'
import { useToast } from '../context/ToastContext'
import { ApiError } from '../services/apiClient'
import type { SessionSummary } from '../types'
import { Skeleton } from './Skeleton'

interface SessionSidebarProps {
  sessions: SessionSummary[]
  activeSessionId: string | null
  isLoading: boolean
  onSelect: (sessionId: string) => void
  onNew: () => void
  onDelete: (sessionId: string) => Promise<void>
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function SessionRow({
  session,
  isActive,
  onSelect,
  onDelete,
}: {
  session: SessionSummary
  isActive: boolean
  onSelect: () => void
  onDelete: () => Promise<void>
}) {
  const [confirming, setConfirming] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const { showApiError } = useToast()

  async function handleDeleteClick(event: React.MouseEvent) {
    event.stopPropagation()
    if (!confirming) {
      setConfirming(true)
      return
    }

    setIsDeleting(true)
    try {
      await onDelete()
    } catch (err) {
      showApiError(err instanceof ApiError ? err : new ApiError({ code: 'INTERNAL_ERROR', message: 'Delete failed.', status: 0 }))
      setConfirming(false)
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`group flex w-full items-start justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm ${
          isActive
            ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
            : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
        }`}
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{session.title ?? 'New conversation'}</span>
          <span className="block text-xs text-gray-400 dark:text-gray-500">
            {formatTimestamp(session.last_activity_at)}
          </span>
        </span>
        <span
          role="button"
          tabIndex={0}
          onClick={handleDeleteClick}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') handleDeleteClick(event as unknown as React.MouseEvent)
          }}
          title={confirming ? 'Confirm delete?' : 'Delete conversation'}
          className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium opacity-0 group-hover:opacity-100 ${
            confirming ? 'bg-red-600 text-white opacity-100' : 'text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20'
          } ${isDeleting ? 'pointer-events-none opacity-60' : ''}`}
        >
          {isDeleting ? '…' : confirming ? '✓' : '✕'}
        </span>
      </button>
    </li>
  )
}

function SessionSidebarSkeleton() {
  return (
    <div className="space-y-2 px-1 py-2">
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="space-y-1.5 px-1.5 py-1">
          <Skeleton className="h-3.5 w-3/4" />
          <Skeleton className="h-2.5 w-1/3" />
        </div>
      ))}
    </div>
  )
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  isLoading,
  onSelect,
  onNew,
  onDelete,
}: SessionSidebarProps) {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-gray-200 dark:border-gray-800">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white"
        >
          + New conversation
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {isLoading && <SessionSidebarSkeleton />}
        {!isLoading && sessions.length === 0 && (
          <p className="px-1 py-2 text-xs text-gray-400 dark:text-gray-500">No conversations yet.</p>
        )}
        {!isLoading && (
          <ul className="space-y-0.5">
            {sessions.map((session) => (
              <SessionRow
                key={session.id}
                session={session}
                isActive={session.id === activeSessionId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
              />
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
