import { useState } from 'react'
import { useToast } from '../context/ToastContext'
import { ApiError } from '../services/apiClient'
import { NON_TERMINAL_DOCUMENT_STATUSES } from '../types'
import type { DocumentDeleteResponse, DocumentSummary } from '../types'
import { DocumentStatusBadge } from './DocumentStatusBadge'
import { Skeleton } from './Skeleton'

interface DocumentListProps {
  documents: DocumentSummary[]
  onDelete: (documentId: string) => Promise<DocumentDeleteResponse>
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`
}

function DocumentRow({ document, onDelete }: { document: DocumentSummary; onDelete: DocumentListProps['onDelete'] }) {
  const [confirming, setConfirming] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const { showApiError } = useToast()

  // FR-D07/10.4: mid-ingestion documents reject delete with 409
  // DOCUMENT_PROCESSING. Disabling here avoids the common case; the catch
  // below still handles the race where status flips between poll ticks.
  const isMidIngestion = NON_TERMINAL_DOCUMENT_STATUSES.includes(document.status)

  async function handleDeleteClick() {
    if (!confirming) {
      setConfirming(true)
      return
    }

    setIsDeleting(true)
    try {
      await onDelete(document.id)
    } catch (err) {
      showApiError(err instanceof ApiError ? err : new ApiError({ code: 'INTERNAL_ERROR', message: 'Delete failed.', status: 0 }))
      setConfirming(false)
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <tr className="border-b border-gray-100 last:border-0 dark:border-gray-800">
      <td className="px-3 py-2">
        <div className="font-medium text-gray-900 dark:text-gray-100">{document.display_name}</div>
        {document.status === 'FAILED' && document.failure_reason && (
          <div className="text-xs text-red-600 dark:text-red-400">{document.failure_reason}</div>
        )}
      </td>
      <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{formatBytes(document.size_bytes)}</td>
      <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{document.page_count ?? '—'}</td>
      <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{document.chunk_count}</td>
      <td className="px-3 py-2">
        <DocumentStatusBadge status={document.status} />
      </td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          disabled={(isMidIngestion && !confirming) || isDeleting}
          title={isMidIngestion && !confirming ? 'This document is still being processed.' : undefined}
          onClick={handleDeleteClick}
          className={`rounded-md px-2 py-1 text-xs font-medium disabled:opacity-40 ${
            confirming
              ? 'bg-red-600 text-white'
              : 'text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20'
          }`}
        >
          {isDeleting ? 'Deleting…' : confirming ? 'Confirm delete?' : 'Delete'}
        </button>
        {confirming && !isDeleting && (
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="ml-1 rounded-md px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            Cancel
          </button>
        )}
      </td>
    </tr>
  )
}

export function DocumentListSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-800">
      <div className="space-y-3 p-3">
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex items-center gap-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-14" />
            <Skeleton className="h-4 w-10" />
            <Skeleton className="h-4 w-10" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function DocumentList({ documents, onDelete }: DocumentListProps) {
  if (documents.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 rounded-lg border border-dashed border-gray-300 px-6 py-10 text-center text-sm dark:border-gray-700">
        <p className="font-medium text-gray-700 dark:text-gray-300">No documents uploaded yet</p>
        <p className="text-gray-500 dark:text-gray-400">
          Upload a PDF above to let employees start asking questions about it.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-gray-50 text-xs uppercase text-gray-500 dark:bg-gray-900 dark:text-gray-400">
          <tr>
            <th className="px-3 py-2 font-medium">Name</th>
            <th className="px-3 py-2 font-medium">Size</th>
            <th className="px-3 py-2 font-medium">Pages</th>
            <th className="px-3 py-2 font-medium">Chunks</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => (
            <DocumentRow key={document.id} document={document} onDelete={onDelete} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
