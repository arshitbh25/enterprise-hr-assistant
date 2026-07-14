import { useEffect, useRef } from 'react'
import type { useChat } from '../hooks/useChat'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { Skeleton } from './Skeleton'

interface ChatWindowProps {
  chat: ReturnType<typeof useChat>
}

// FR-F02: static starter prompts (a v1 substitute for the SDD's
// document-title-derived suggestions, which need a "top questions"
// backend endpoint this phase doesn't have) - covers the most common HR
// lookup categories from Section 1.1 so a first-time user has something
// to click besides a blank box.
const STARTER_QUESTIONS = [
  'How many casual leaves do I get per year?',
  'What is the notice period for my role?',
  'Can I claim internet reimbursement while on WFH?',
  'How do I apply for parental leave?',
]

function EmptyState({ onPick, disabled }: { onPick: (question: string) => void; disabled: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <p className="max-w-sm text-sm text-gray-500 dark:text-gray-400">
        Ask your first question about HR policy — leave, reimbursement, code of conduct, and more.
      </p>
      <div className="flex flex-wrap justify-center gap-2 px-4">
        {STARTER_QUESTIONS.map((question) => (
          <button
            key={question}
            type="button"
            disabled={disabled}
            onClick={() => onPick(question)}
            className="rounded-full border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  )
}

function HistorySkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Skeleton className="h-9 w-2/5 rounded-2xl" />
      </div>
      <div className="flex justify-start">
        <Skeleton className="h-16 w-3/5 rounded-2xl" />
      </div>
      <div className="flex justify-end">
        <Skeleton className="h-9 w-1/3 rounded-2xl" />
      </div>
    </div>
  )
}

export function ChatWindow({ chat }: ChatWindowProps) {
  const { messages, isLoading, isHistoryLoading, sendMessage } = chat
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {isHistoryLoading && <HistorySkeleton />}
        {!isHistoryLoading && messages.length === 0 && (
          <EmptyState onPick={sendMessage} disabled={isLoading} />
        )}
        {!isHistoryLoading && messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="max-w-[75%] rounded-2xl rounded-bl-sm bg-gray-100 px-4 py-3 text-sm text-gray-500 dark:bg-gray-800 dark:text-gray-400">
              Thinking…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <ChatInput onSend={sendMessage} disabled={isLoading || isHistoryLoading} />
    </div>
  )
}
