// Mirrors backend/app/api/schemas/upload.py

export interface UploadFileError {
  code: string
  message: string
}

export interface UploadFileResult {
  file_name: string
  document_id: string | null
  status: string
  error: UploadFileError | null
}

export interface UploadResponse {
  results: UploadFileResult[]
  request_id: string | null
}
