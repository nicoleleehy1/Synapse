import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadPDF, getDocumentStatus } from '../api/client'
import type { DocumentStatus } from '../types/graph'

export function useDocumentUpload() {
  const [uploading, setUploading] = useState(false)
  const [status, setStatus] = useState<DocumentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => () => stopPoll(), [])

  const upload = useCallback(async (file: File) => {
    setUploading(true)
    setError(null)
    setStatus(null)
    stopPoll()

    try {
      const { document_id } = await uploadPDF(file)

      setStatus({
        document_id,
        filename: file.name,
        status: 'processing',
        page_count: 0,
        chunk_count: 0,
        entity_count: 0,
        relationship_count: 0,
      })

      pollRef.current = setInterval(async () => {
        try {
          const s = await getDocumentStatus(document_id)
          setStatus(s)
          if (s.status === 'complete' || s.status === 'error') {
            stopPoll()
            setUploading(false)
          }
        } catch {
          // tolerate transient errors
        }
      }, 2000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Upload failed'
      setError(msg)
      setUploading(false)
    }
  }, [])

  return { upload, uploading, status, error }
}
