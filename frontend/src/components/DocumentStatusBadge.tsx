import { MID_INGESTION_DOCUMENT_STATUSES } from '../types'
import type { DocumentStatus } from '../types'

const LABELS: Record<DocumentStatus, string> = {
  UPLOADED: 'Queued',
  PARSING: 'Parsing',
  CHUNKING: 'Chunking',
  EMBEDDING: 'Embedding',
  READY: 'Ready',
  FAILED: 'Failed',
}

const STYLES: Record<DocumentStatus, string> = {
  UPLOADED: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  PARSING: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  CHUNKING: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  EMBEDDING: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  READY: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  FAILED: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const isMidIngestion = MID_INGESTION_DOCUMENT_STATUSES.includes(status)

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[status]}`}
    >
      {isMidIngestion && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {LABELS[status]}
    </span>
  )
}
