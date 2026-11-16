import { useCallback, useEffect, useRef, useState } from 'react'
import { documentEventsUrl, errorMessage, getDocumentStatus, uploadPDF } from '../api/client'
import { isTerminal } from '../lib/progress'
import type { DocumentStatus } from '../types/graph'

/**
 * Upload a PDF and follow its processing live.
 *
 * Progress arrives over Server-Sent Events; if the stream can't be opened
 * (old proxy, network blip) it falls back to polling the status endpoint.
 */
export function useDocumentUpload() {
  const [uploading, setUploading] = useState(false)
  const [status, setStatus] = useState<DocumentStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const sourceRef = useRef<EventSource | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stop = useCallback(() => {
    sourceRef.current?.close()
    sourceRef.current = null
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
  }, [])

  useEffect(() => stop, [stop])

  const accept = useCallback((s: DocumentStatus) => {
    setStatus(s)
    if (isTerminal(s)) {
      stop()
      setUploading(false)
    }
  }, [stop])

  const poll = useCallback((documentId: string) => {
    if (pollRef.current) return
    pollRef.current = setInterval(async () => {
      try {
        accept(await getDocumentStatus(documentId))
      } catch {
        // tolerate transient errors
      }
    }, 2000)
  }, [accept])

  const follow = useCallback((documentId: string) => {
    if (typeof EventSource === 'undefined') return poll(documentId)
    const es = new EventSource(documentEventsUrl(documentId))
    sourceRef.current = es
    es.addEventListener('status', (ev) => {
      try {
        accept(JSON.parse((ev as MessageEvent).data))
      } catch {
        // ignore malformed frames
      }
    })
    es.onerror = () => {
      // The server closes the stream after the final status; anything else
      // (or a stream that never opened) degrades to polling.
      es.close()
      if (sourceRef.current === es) {
        sourceRef.current = null
        poll(documentId)
      }
    }
  }, [accept, poll])

  const upload = useCallback(async (file: File) => {
    stop()
    setUploading(true)
    setError(null)
    setStatus(null)
    try {
      const { document_id } = await uploadPDF(file)
      setStatus({
        document_id,
        filename: file.name,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        chunks_processed: 0,
        page_count: 0,
        chunk_count: 0,
        entity_count: 0,
        relationship_count: 0,
      })
      follow(document_id)
    } catch (e: unknown) {
      setError(errorMessage(e, 'Upload failed'))
      setUploading(false)
    }
  }, [follow, stop])

  return { upload, uploading, status, error }
}
