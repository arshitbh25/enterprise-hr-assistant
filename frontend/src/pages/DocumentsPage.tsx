import { DocumentList, DocumentListSkeleton } from '../components/DocumentList'
import { UploadDropzone } from '../components/UploadDropzone'
import { useDocuments } from '../hooks/useDocuments'

export function DocumentsPage() {
  const { documents, isLoading, isUploading, uploadFiles, deleteDocument } = useDocuments()

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-6 overflow-y-auto p-4">
      <div>
        <h2 className="text-lg font-semibold">HR Policy Documents</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Upload PDF policy documents so employees can ask questions about them.
        </p>
      </div>

      <UploadDropzone onUpload={uploadFiles} isUploading={isUploading} />

      {isLoading ? (
        <DocumentListSkeleton />
      ) : (
        <DocumentList documents={documents} onDelete={deleteDocument} />
      )}
    </div>
  )
}
