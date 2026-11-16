import axios from 'axios'
import { readSSE } from '../lib/sse'
import type {
  AgentEvent, Topic,
  DocumentStatus, GraphData, QueryResponse,
  CreateNodePayload, UpdateNodePayload, CreateEdgePayload, GraphEdge, GraphNode,
  OrphanInfo, EdgeOrphanInfo,
} from '../types/graph'

/** API origin: same-origin `/api` behind nginx/Vite, or an absolute URL in split deployments. */
export const API_BASE = resolveApiBase(import.meta.env.VITE_API_URL)

export function resolveApiBase(raw: string | undefined): string {
  const v = raw?.trim().replace(/\/$/, '')
  if (!v) return '/api'
  // Hosting platforms often expose a bare hostname; assume HTTPS.
  return /^https?:\/\//.test(v) || v.startsWith('/') ? v : `https://${v}`
}

const api = axios.create({ baseURL: API_BASE })

/** Human-readable message from an API error (FastAPI puts it in `detail`). */
export function errorMessage(e: unknown, fallback = 'Something went wrong'): string {
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (e.response?.status === 413) return 'That PDF is too large.'
    if (e.response?.status === 429) return 'Rate limit reached. Please try again later.'
    return e.message || fallback
  }
  return e instanceof Error ? e.message : fallback
}

/** URL of the Server-Sent Events stream for a document's processing progress. */
export function documentEventsUrl(documentId: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(documentId)}/events`
}

export async function uploadPDF(file: File): Promise<{ document_id: string; filename: string }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post('/documents/upload', form)
  return data
}

export async function getDocumentStatus(documentId: string): Promise<DocumentStatus> {
  const { data } = await api.get(`/documents/${documentId}/status`)
  return data
}

export async function listDocuments(): Promise<DocumentStatus[]> {
  const { data } = await api.get('/documents/')
  return data
}

export async function deleteDocument(documentId: string): Promise<void> {
  await api.delete(`/documents/${documentId}`)
}

export async function getFullGraph(documentId?: string): Promise<GraphData> {
  const params = documentId ? { document_id: documentId } : {}
  const { data } = await api.get('/graph/', { params })
  return data
}

export async function getEntityNeighbourhood(entityId: string, depth = 2): Promise<GraphData> {
  const { data } = await api.get(`/graph/entity/${entityId}`, { params: { depth } })
  return data
}

export async function runCypher(cypher: string, params?: Record<string, unknown>): Promise<unknown[]> {
  const { data } = await api.post('/graph/cypher', { cypher, params })
  return data
}

export async function queryGraph(
  query: string,
  documentId?: string,
  topK = 5,
): Promise<QueryResponse> {
  const { data } = await api.post('/query/', {
    query,
    document_id: documentId,
    top_k: topK,
    hop_depth: 2,
  })
  return data
}

// ── Graph mutations ────────────────────────────────────────────────────────

export async function createNode(payload: CreateNodePayload): Promise<GraphData> {
  const { data } = await api.post('/graph/nodes', payload)
  return data
}

export async function updateNode(entityId: string, payload: UpdateNodePayload): Promise<GraphNode> {
  const { data } = await api.patch(`/graph/nodes/${entityId}`, payload)
  return data
}

export async function createEdge(payload: CreateEdgePayload): Promise<GraphEdge> {
  const { data } = await api.post('/graph/edges', payload)
  return data
}

export async function getNodeOrphans(entityId: string): Promise<OrphanInfo> {
  const { data } = await api.get(`/graph/nodes/${entityId}/orphans`)
  return data
}

export async function getEdgeOrphanTarget(edgeId: string): Promise<EdgeOrphanInfo> {
  const { data } = await api.get(`/graph/edges/${edgeId}/orphan-target`)
  return data
}

export async function deleteNode(entityId: string, cascade: boolean): Promise<void> {
  await api.delete(`/graph/nodes/${entityId}`, { params: { cascade } })
}

export async function deleteEdge(edgeId: string, cascade: boolean): Promise<void> {
  await api.delete(`/graph/edges/${edgeId}`, { params: { cascade } })
}

// ── GraphRAG agent ─────────────────────────────────────────────────────────

/** Ask the GraphRAG agent; events (steps, answer tokens, final result) stream to `onEvent`. */
export async function streamQuery(
  query: string,
  onEvent: (event: AgentEvent) => void,
  opts: { documentId?: string; signal?: AbortSignal } = {},
): Promise<void> {
  const res = await fetch(`${API_BASE}/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ query, document_id: opts.documentId }),
    signal: opts.signal,
  })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { detail = (await res.json()).detail ?? detail } catch { /* not JSON */ }
    if (res.status === 429) detail = 'Rate limit reached. Please try again later.'
    throw new Error(detail)
  }
  await readSSE(res, ({ data }) => {
    try {
      onEvent(JSON.parse(data) as AgentEvent)
    } catch {
      // ignore keep-alives / malformed frames
    }
  }, opts.signal)
}

export async function listTopics(): Promise<Topic[]> {
  const { data } = await api.get('/graph/topics')
  return data
}
