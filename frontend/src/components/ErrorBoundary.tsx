import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
}

// Only a class component can implement getDerivedStateFromError/
// componentDidCatch - there is no hook equivalent, so this is the one
// deliberate exception to the rest of the app's function-component style.
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Uncaught render error', error, info.componentStack)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-white p-6 text-center dark:bg-gray-950">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Something went wrong</h1>
        <p className="max-w-sm text-sm text-gray-500 dark:text-gray-400">
          The app hit an unexpected error. Reloading the page usually fixes it.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white"
        >
          Reload
        </button>
      </div>
    )
  }
}
