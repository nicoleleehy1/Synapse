import type { DocumentStatus, PipelineStage } from '../types/graph'

const STAGE_LABELS: Record<PipelineStage, string> = {
  queued: 'Queued',
  parsing: 'Reading PDF',
  chunking: 'Splitting into passages',
  embedding: 'Embedding passages',
  extracting: 'Extracting entities and relationships',
  resolving: 'Merging duplicate entities',
  writing: 'Writing the graph',
  done: 'Done',
}

export function stageLabel(s: Pick<DocumentStatus, 'stage' | 'chunks_processed' | 'chunk_count'>): string {
  const base = STAGE_LABELS[s.stage] ?? s.stage
  if (s.stage === 'extracting' && s.chunk_count > 0) {
    return `${base} (${s.chunks_processed}/${s.chunk_count})`
  }
  return base
}

export function progressPercent(progress: number): number {
  if (!Number.isFinite(progress)) return 0
  return Math.round(Math.min(1, Math.max(0, progress)) * 100)
}

export function isTerminal(s: Pick<DocumentStatus, 'status'> | null | undefined): boolean {
  return s?.status === 'complete' || s?.status === 'error'
}
