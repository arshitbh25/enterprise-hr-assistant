/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_MAX_FILE_MB?: string
  readonly VITE_MAX_FILES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
