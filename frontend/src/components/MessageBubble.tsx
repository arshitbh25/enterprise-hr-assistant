import type { ChatMessage } from '../types'
import { CitationCard } from './CitationCard'
import { ConfidenceBadge } from './ConfidenceBadge'

// FR-Q08: every assistant answer carries this disclaimer. ChatResponse has
// no separate field for it (the backend bakes HR_DISCLAIMER into the
// answer prose), so it's rendered as its own subtly-styled element here
// rather than parsed out of the model's text - reliable regardless of
// phrasing.
const DISCLAIMER = 'HR remains the final authority on all policy matters.'

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-white">
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        </div>
      </div>
    )
  }

  const isRefusal = message.notFound

  return (
    <div className="flex justify-start">
      <div
        className={`max-w-[75%] rounded-2xl rounded-bl-sm px-4 py-3 ${
          isRefusal
            ? 'border border-amber-300 bg-amber-50 dark:border-amber-700/60 dark:bg-amber-900/20'
            : 'bg-gray-100 dark:bg-gray-800'
        }`}
      >
        <p className="whitespace-pre-wrap text-sm text-gray-900 dark:text-gray-100">{message.content}</p>

        {message.confidence === 'low' && (
          <div className="mt-2">
            <ConfidenceBadge confidence={message.confidence} />
          </div>
        )}

        {message.citations.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {message.citations.map((citation, index) => (
              <CitationCard key={`${citation.document_name}-${index}`} citation={citation} />
            ))}
          </div>
        )}

        <p className="mt-2 text-[11px] text-gray-400 dark:text-gray-500">{DISCLAIMER}</p>
      </div>
    </div>
  )
}
