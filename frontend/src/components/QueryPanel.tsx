import { useState } from 'react'
import { Loader2, ChevronDown, ChevronUp } from 'lucide-react'
import { queryGraph } from '../api/client'
import type { QueryResponse, GraphData } from '../types/graph'

interface Props {
  documentId?: string
  onGraphContext: (data: GraphData) => void
}

export function QueryPanel({ documentId, onGraphContext }: Props) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<QueryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showSources, setShowSources] = useState(false)
  const [showCypher, setShowCypher] = useState(false)

  const submit = async () => {
    if (!query.trim() || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await queryGraph(query, documentId, 5)
      setResult(res)
      onGraphContext(res.graph_context)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Query failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Input row */}
      <div className="flex gap-2">
        <input
          className="flex-1 border border-border rounded px-3 py-2 text-sm text-foreground placeholder-chart-2 focus:outline-none focus:border-chart-3 bg-background transition-colors"
          placeholder="Ask anything about your document…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          disabled={loading}
        />
        <button
          onClick={submit}
          disabled={loading || !query.trim()}
          className="px-4 py-2 bg-foreground text-background text-sm font-medium rounded hover:bg-chart-4 disabled:opacity-30 transition-colors whitespace-nowrap"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : 'Ask'}
        </button>
      </div>

      {error && (
        <p className="text-xs text-foreground border border-border rounded px-3 py-2 bg-secondary">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-4">
          {/* Answer */}
          <div>
            <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest mb-2">
              Answer
            </p>
            <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
              {result.answer}
            </p>
          </div>

          <div className="border-t border-border" />

          {/* Sources */}
          {result.sources.length > 0 && (
            <div>
              <button
                className="flex items-center justify-between w-full text-left group"
                onClick={() => setShowSources((v) => !v)}
              >
                <span className="text-2xs font-semibold text-chart-2 uppercase tracking-widest group-hover:text-foreground transition-colors">
                  {result.sources.length} Source Chunks
                </span>
                {showSources
                  ? <ChevronUp size={12} className="text-chart-2" />
                  : <ChevronDown size={12} className="text-chart-2" />
                }
              </button>
              {showSources && (
                <div className="mt-2 space-y-2">
                  {result.sources.map((s, i) => (
                    <div key={s.chunk_id} className="border border-border rounded p-3">
                      <div className="flex justify-between mb-1">
                        <span className="text-2xs text-chart-2">
                          [{i + 1}] {s.document_name} · p.{s.page_number}
                        </span>
                        <span className="text-2xs text-chart-3 font-medium">
                          {(s.similarity_score * 100).toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-xs text-chart-3 leading-relaxed line-clamp-4">
                        {s.text}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Cypher */}
          {result.cypher_used && (
            <div>
              <button
                className="flex items-center justify-between w-full text-left group"
                onClick={() => setShowCypher((v) => !v)}
              >
                <span className="text-2xs font-semibold text-chart-2 uppercase tracking-widest group-hover:text-foreground transition-colors">
                  Cypher Query
                </span>
                {showCypher
                  ? <ChevronUp size={12} className="text-chart-2" />
                  : <ChevronDown size={12} className="text-chart-2" />
                }
              </button>
              {showCypher && (
                <pre className="mt-2 border border-border rounded p-3 text-2xs font-mono text-chart-3 overflow-x-auto whitespace-pre-wrap bg-secondary">
                  {result.cypher_used}
                </pre>
              )}
            </div>
          )}

          <p className="text-2xs text-chart-1">
            {result.graph_context.nodes.length} nodes · {result.graph_context.edges.length} edges highlighted
          </p>
        </div>
      )}
    </div>
  )
}
