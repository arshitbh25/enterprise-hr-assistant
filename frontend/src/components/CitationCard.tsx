import { useState } from 'react'
import type { Citation } from '../types'

export function CitationCard({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false)
  const pageLabel =
    citation.pages.length > 1
      ? `pp. ${citation.pages[0]}–${citation.pages[citation.pages.length - 1]}`
      : `p. ${citation.pages[0]}`

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 text-sm dark:border-gray-700 dark:bg-gray-800/50">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
      >
        <span className="min-w-0 truncate">
          <span className="font-medium text-gray-800 dark:text-gray-200">{citation.document_name}</span>
          <span className="text-gray-500 dark:text-gray-400">
            {' · '}
            {pageLabel}
            {citation.section ? ` · ${citation.section}` : ''}
          </span>
        </span>
        <span className="shrink-0 text-gray-400">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && citation.snippet && (
        <p className="border-t border-gray-200 px-3 py-2 text-gray-600 dark:border-gray-700 dark:text-gray-300">
          {citation.snippet}
        </p>
      )}
    </div>
  )
}
