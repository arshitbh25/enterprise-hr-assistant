import { useCallback, useRef, useState } from 'react'
import { friendlyMessageFor } from '../services/errorMessages'
import type { UploadFileResult } from '../types'

// Falls back to the backend defaults (Settings.upload_max_file_mb /
// upload_max_files) so pre-checks stay correct even with no .env override -
// the env vars just let a deployment tune them without a frontend rebuild.
const MAX_FILES = Number(import.meta.env.VITE_MAX_FILES ?? 10)
const MAX_FILE_MB = Number(import.meta.env.VITE_MAX_FILE_MB ?? 25)
const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

interface ClientRejection {
  file_name: string
  message: string
}

interface UploadDropzoneProps {
  onUpload: (files: File[]) => Promise<UploadFileResult[]>
  isUploading: boolean
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export function UploadDropzone({ onUpload, isUploading }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [results, setResults] = useState<UploadFileResult[]>([])
  const [clientRejections, setClientRejections] = useState<ClientRejection[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  const submitFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const files = Array.from(fileList)
      if (files.length === 0) return

      setResults([])

      const accepted: File[] = []
      const rejected: ClientRejection[] = []
      for (const file of files) {
        if (!isPdf(file)) {
          rejected.push({ file_name: file.name, message: friendlyMessageFor('INVALID_FILE_TYPE', 'Only PDF files are accepted.') })
        } else if (file.size > MAX_FILE_BYTES) {
          rejected.push({ file_name: file.name, message: friendlyMessageFor('FILE_TOO_LARGE', 'That file is too large to upload.') })
        } else {
          accepted.push(file)
        }
      }

      if (accepted.length > MAX_FILES) {
        for (const file of accepted.splice(MAX_FILES)) {
          rejected.push({ file_name: file.name, message: `Only ${MAX_FILES} files may be uploaded at once.` })
        }
      }

      setClientRejections(rejected)
      if (accepted.length > 0) {
        setResults(await onUpload(accepted))
      }
    },
    [onUpload],
  )

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setIsDragging(false)
          void submitFiles(event.dataTransfer.files)
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
          isDragging
            ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
            : 'border-gray-300 dark:border-gray-700'
        }`}
      >
        <p className="text-sm text-gray-600 dark:text-gray-300">
          Drag and drop PDF policy documents here, or
        </p>
        <button
          type="button"
          disabled={isUploading}
          onClick={() => inputRef.current?.click()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {isUploading ? 'Uploading…' : 'Browse files'}
        </button>
        <p className="text-xs text-gray-400 dark:text-gray-500">
          PDF only · up to {MAX_FILE_MB} MB each · up to {MAX_FILES} files at once
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(event) => {
            if (event.target.files) void submitFiles(event.target.files)
            event.target.value = ''
          }}
        />
      </div>

      {(clientRejections.length > 0 || results.length > 0) && (
        <ul className="space-y-1 text-sm">
          {clientRejections.map((rejection, index) => (
            <li key={`client-${index}`} className="flex items-center gap-2 text-red-600 dark:text-red-400">
              <span aria-hidden>✕</span>
              <span className="font-medium">{rejection.file_name}</span>
              <span className="text-gray-500 dark:text-gray-400">— {rejection.message}</span>
            </li>
          ))}
          {results.map((result, index) => (
            <li
              key={`result-${index}`}
              className={`flex items-center gap-2 ${
                result.status === 'REJECTED' ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
              }`}
            >
              <span aria-hidden>{result.status === 'REJECTED' ? '✕' : '✓'}</span>
              <span className="font-medium">{result.file_name}</span>
              <span className="text-gray-500 dark:text-gray-400">
                — {result.status === 'REJECTED' && result.error
                  ? friendlyMessageFor(result.error.code, result.error.message)
                  : 'Upload accepted, processing started'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
