export interface GraphNode {
  id: string
  name: string
  type: string
  description?: string
  source_document: string
  chunk_count: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: string
  description?: string
  confidence: number
  source_document: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export type DocumentState = 'queued' | 'processing' | 'complete' | 'error'
export type PipelineStage =
  | 'queued' | 'parsing' | 'chunking' | 'embedding' | 'extracting' | 'resolving' | 'writing' | 'done'

export interface DocumentStatus {
  document_id: string
  filename: string
  status: DocumentState
  stage: PipelineStage
  progress: number
  chunks_processed: number
  created_at?: string
  updated_at?: string
  page_count: number
  chunk_count: number
  entity_count: number
  relationship_count: number
  error?: string
}

export interface SourceChunk {
  chunk_id: string
  text: string
  page_number: number
  document_name: string
  similarity_score: number
}

export interface QueryResponse {
  answer: string
  sources: SourceChunk[]
  graph_context: GraphData
  cypher_used?: string
}

// react-force-graph-2d node/link format
export interface FGNode extends GraphNode {
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number
  fy?: number
  color?: string
  textColor?: string
  val?: number
}

export interface FGLink {
  id: string
  source: string | FGNode
  target: string | FGNode
  type: string
  description?: string
  confidence: number
  source_document: string
  color?: string
}

export interface FGData {
  nodes: FGNode[]
  links: FGLink[]
}

// Mutation payloads
export interface CreateNodePayload {
  name: string
  type: string
  description?: string
  parent_entity_id?: string
  relationship_type?: string
  relationship_direction?: 'out' | 'in'
  confidence?: number
}

export interface UpdateNodePayload {
  name?: string
  type?: string
  description?: string
}

export interface CreateEdgePayload {
  source_entity_id: string
  target_entity_id: string
  type: string
  description?: string
  confidence: number
}

export interface OrphanInfo {
  orphaned_nodes: GraphNode[]
}

export interface EdgeOrphanInfo {
  orphaned_target: GraphNode | null
}

// ── GraphRAG agent stream ─────────────────────────────────────────────────────

export type AgentTool =
  | 'search_passages' | 'search_entities' | 'explore_entities' | 'search_topics' | 'run_cypher'

export interface AgentStep {
  id: string
  tool: AgentTool | string
  input: Record<string, unknown>
  summary?: string
  is_error?: boolean
}

export interface AgentDone {
  answer: string
  sources: SourceChunk[]
  graph: GraphData
  highlight_ids: string[]
  steps: number
  latency_ms: number
}

export type AgentEvent =
  | ({ type: 'step' } & AgentStep)
  | { type: 'step_result'; id: string; summary: string; is_error: boolean }
  | { type: 'text'; delta: string }
  | { type: 'text_reset' }
  | ({ type: 'done' } & AgentDone)
  | { type: 'error'; message: string }

export interface Topic {
  id: string
  level: number
  title: string
  summary: string
  findings: string[]
  size: number
  parent_id: string | null
  member_ids: string[]
}
