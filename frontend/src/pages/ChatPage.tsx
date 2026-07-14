import { useEffect, useState } from 'react'
import { ChatWindow } from '../components/ChatWindow'
import { SessionSidebar } from '../components/SessionSidebar'
import { useChat } from '../hooks/useChat'
import { useSessions } from '../hooks/useSessions'

export function ChatPage() {
  const chat = useChat()
  const sessions = useSessions()
  const { refresh: refreshSessions } = sessions
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  // A completed turn may create a session or change its title/last-activity
  // (Section 8.3) - refresh the sidebar whenever the turn count changes.
  // Silent: a background re-fetch failing here isn't worth a toast.
  useEffect(() => {
    refreshSessions({ silent: true })
  }, [chat.messages.length, refreshSessions])

  async function handleSelectSession(sessionId: string) {
    await chat.loadSession(sessionId)
    setIsSidebarOpen(false)
  }

  function handleNewSession() {
    chat.startNewSession()
    setIsSidebarOpen(false)
  }

  async function handleDeleteSession(sessionId: string) {
    await sessions.deleteSession(sessionId)
    if (sessionId === chat.sessionId) chat.startNewSession()
  }

  return (
    <div className="flex h-full">
      {/* Mobile-only backdrop behind the off-canvas sidebar */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/30 md:hidden"
          onClick={() => setIsSidebarOpen(false)}
          aria-hidden
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-40 transition-transform md:static md:z-auto md:translate-x-0 ${
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <SessionSidebar
          sessions={sessions.sessions}
          activeSessionId={chat.sessionId}
          isLoading={sessions.isLoading}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          onDelete={handleDeleteSession}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <button
          type="button"
          onClick={() => setIsSidebarOpen(true)}
          aria-label="Show conversations"
          className="m-2 flex w-fit items-center gap-1.5 rounded-md px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 md:hidden dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <span aria-hidden>☰</span> Conversations
        </button>
        <div className="min-h-0 flex-1">
          <ChatWindow chat={chat} />
        </div>
      </div>
    </div>
  )
}
