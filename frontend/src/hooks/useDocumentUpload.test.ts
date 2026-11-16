import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DocumentStatus } from '../types/graph'
import { useDocumentUpload } from './useDocumentUpload'

vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  uploadPDF: vi.fn(async (file: File) => ({ document_id: 'doc-1', filename: file.name })),
  getDocumentStatus: vi.fn(),
}))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {}
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) { FakeEventSource.instances.push(this) }
  addEventListener(type: string, fn: (ev: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn)
  }
  close() { this.closed = true }
  emit(status: Partial<DocumentStatus>) {
    this.listeners.status?.forEach(fn => fn({ data: JSON.stringify(status) } as MessageEvent))
  }
}

const base: DocumentStatus = {
  document_id: 'doc-1', filename: 'a.pdf', status: 'processing', stage: 'extracting',
  progress: 0.4, chunks_processed: 2, page_count: 3, chunk_count: 5, entity_count: 0, relationship_count: 0,
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

describe('useDocumentUpload', () => {
  it('follows live progress over SSE until the job completes', async () => {
    const { result } = renderHook(() => useDocumentUpload())
    await act(() => result.current.upload(new File(['%PDF-'], 'a.pdf')))

    expect(result.current.uploading).toBe(true)
    expect(result.current.status?.stage).toBe('queued')
    const es = FakeEventSource.instances[0]
    expect(es.url).toBe('/api/documents/doc-1/events')

    act(() => es.emit(base))
    expect(result.current.status?.progress).toBe(0.4)

    act(() => es.emit({ ...base, status: 'complete', stage: 'done', progress: 1, entity_count: 9 }))
    await waitFor(() => expect(result.current.uploading).toBe(false))
    expect(result.current.status?.entity_count).toBe(9)
    expect(es.closed).toBe(true)
  })

  it('falls back to polling when the stream fails', async () => {
    vi.useFakeTimers()
    const { getDocumentStatus } = await import('../api/client')
    vi.mocked(getDocumentStatus).mockResolvedValue({ ...base, status: 'complete', stage: 'done', progress: 1 })

    const { result } = renderHook(() => useDocumentUpload())
    await act(() => result.current.upload(new File(['%PDF-'], 'a.pdf')))
    act(() => FakeEventSource.instances[0].onerror?.())
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })

    expect(getDocumentStatus).toHaveBeenCalledWith('doc-1')
    expect(result.current.status?.status).toBe('complete')
    expect(result.current.uploading).toBe(false)
    vi.useRealTimers()
  })
})
