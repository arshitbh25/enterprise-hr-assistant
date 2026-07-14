import { useState } from 'react'

interface ChatInputProps {
  onSend: (question: string) => void
  disabled: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState('')

  function submit(event: { preventDefault: () => void }) {
    event.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }

  return (
    <form
      onSubmit={submit}
      className="flex items-end gap-2 border-t border-gray-200 p-3 dark:border-gray-800"
    >
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            submit(event)
          }
        }}
        placeholder="Ask a question about HR policy…"
        rows={1}
        maxLength={2000}
        disabled={disabled}
        className="min-h-10 flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {disabled ? 'Sending…' : 'Send'}
      </button>
    </form>
  )
}
