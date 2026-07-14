import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Citation } from '../types'
import { CitationCard } from './CitationCard'

const citation: Citation = {
  document_name: 'Leave_Policy_2026.pdf',
  pages: [4],
  section: 'Casual Leave',
  snippet: 'Employees are entitled to 12 casual leaves per calendar year.',
}

describe('CitationCard', () => {
  it('renders collapsed with the doc/page/section label, then reveals the snippet on click', () => {
    render(<CitationCard citation={citation} />)

    expect(screen.getByText('Leave_Policy_2026.pdf')).toBeInTheDocument()
    expect(screen.getByText(/p\. 4/)).toBeInTheDocument()
    expect(screen.getByText(/Casual Leave/)).toBeInTheDocument()
    expect(screen.queryByText(citation.snippet)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText(citation.snippet)).toBeInTheDocument()
  })
})
