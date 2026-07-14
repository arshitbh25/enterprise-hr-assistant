import type { ConfidenceLevel } from '../types'

// FR-Q03/6.3.7: 'high' gets no badge (a clean, trusted answer); 'low' gets
// a subtle caution badge; 'not_found' is rendered as a distinctly-styled
// bubble by MessageBubble instead of a badge, so it's a no-op here.
export function ConfidenceBadge({ confidence }: { confidence: ConfidenceLevel }) {
  if (confidence !== 'low') return null

  return (
    <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
      Low confidence — please verify with HR
    </span>
  )
}
