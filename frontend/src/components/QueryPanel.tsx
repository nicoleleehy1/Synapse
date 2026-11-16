import { useCallback, useState } from 'react'
import {
  AlertTriangle, BookOpen, Check, ChevronDown, ChevronUp, Database, Layers, Loader2, Network, Search, Square,
} from 'lucide-react'
import { useAgentQuery } from '../hooks/useAgentQuery'
import { splitCitations } from '../lib/citations'
import type { AgentDone, AgentStep } from '../types/graph'

interface Props {
  documentId?: string
  onResult: (result: AgentDone) => void
}

const TOOL_META: Record<string, { label: string; icon: typeof Search }> = {
  search_passages: { label: 'Search passages', icon: BookOpen },
  search_entities: { label: 'Find entities', icon: Search },
  explore_entities: { label: 'Explore graph', icon: Network },
  search_topics: { label: 'Read topic reports', icon: Layers },
  run_cypher: { label: 'Run Cypher', icon: Database },
}

const EXAMPLES = [
  'What are the main themes across my documents?',
  'How is the most connected entity related to the others?',
  'Which organizations are mentioned most often?',
]

export function QueryPanel({ documentId, onResult }: Props) {
  const [query, setQuery] = useState('')
  const [openSource, setOpenSource] = useState<number | null>(null)
  const [showTrace, setShowTrace] = useState(true)
  const { state, ask, cancel } = useAgentQuery(useCallback((r: AgentDone) => onResult(r), [onResult]))
  const running = state.status === 'running'

  const submit = (q = query) => {
    if (!q.trim() || running) return
    setQuery(q)
    setOpenSource(null)
    void ask(q.trim(), documentId)
  }

  const sources = state.result?.sources ?? []

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          className="flex-1 min-w-0 border border-border rounded-sm px-3 py-2 text-sm text-foreground placeholder-chart-2 focus:outline-hidden focus:border-chart-3 bg-background transition-colors"
          placeholder="Ask anything about your documents…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          disabled={running}
          aria-label="Question"
        />
        {running ? (
          <button
            onClick={cancel}
            className="px-3 py-2 border border-border text-sm rounded-sm hover:bg-secondary transition-colors"
            aria-label="Stop"
            title="Stop"
          >
            <Square size={12} />
          </button>
        ) : (
          <button
            onClick={() => submit()}
            disabled={!query.trim()}
            className="px-4 py-2 bg-foreground text-background text-sm font-medium rounded-sm hover:bg-chart-4 disabled:opacity-30 transition-colors whitespace-nowrap"
          >
            Ask
          </button>
        )}
      </div>

      {state.status === 'idle' && (
        <div className="flex flex-col gap-1.5">
          {EXAMPLES.map(ex => (
            <button
              key={ex}
              onClick={() => submit(ex)}
              className="text-left text-xs text-chart-3 hover:text-foreground transition-colors"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* Reasoning trace */}
      {state.steps.length > 0 && (
        <div>
          <button
            className="flex items-center justify-between w-full text-left group"
            onClick={() => setShowTrace(v => !v)}
          >
            <span className="text-2xs font-semibold text-chart-2 uppercase tracking-widest group-hover:text-foreground transition-colors">
              Reasoning · {state.steps.length} step{state.steps.length === 1 ? '' : 's'}
            </span>
            {showTrace ? <ChevronUp size={12} className="text-chart-2" /> : <ChevronDown size={12} className="text-chart-2" />}
          </button>
          {showTrace && (
            <ol className="mt-2 space-y-1.5" aria-live="polite">
              {state.steps.map(step => <StepRow key={step.id} step={step} />)}
            </ol>
          )}
        </div>
      )}

      {running && state.steps.length === 0 && !state.answer && (
        <div className="flex items-center gap-2 text-xs text-chart-2">
          <Loader2 size={11} className="animate-spin" /> Planning…
        </div>
      )}

      {state.error && (
        <p className="text-xs text-foreground border border-border rounded-sm px-3 py-2 bg-secondary">{state.error}</p>
      )}

      {/* Answer, streamed, with clickable citations */}
      {state.answer && (
        <div>
          <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest mb-2">Answer</p>
          <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
            {splitCitations(state.answer).map((part, i) =>
              part.kind === 'text' ? (
                <span key={i}>{part.text}</span>
              ) : (
                <button
                  key={i}
                  onClick={() => setOpenSource(openSource === part.n ? null : part.n)}
                  className={`mx-0.5 inline-flex items-center justify-center min-w-[1.25rem] h-4 px-1 text-2xs font-semibold rounded-sm align-text-top transition-colors ${
                    openSource === part.n ? 'bg-foreground text-background' : 'bg-secondary text-chart-4 hover:bg-chart-1'
                  }`}
                  title={sources[part.n - 1] ? `${sources[part.n - 1].document_name}, p.${sources[part.n - 1].page_number}` : 'Source'}
                >
                  {part.n}
                </button>
              ),
            )}
            {running && <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-foreground animate-pulse align-text-bottom" />}
          </p>
        </div>
      )}

      {openSource !== null && sources[openSource - 1] && (
        <blockquote className="border-l-2 border-foreground pl-3 py-1">
          <p className="text-2xs text-chart-2 mb-1">
            [{openSource}] {sources[openSource - 1].document_name} · page {sources[openSource - 1].page_number}
          </p>
          <p className="text-xs text-chart-4 leading-relaxed">{sources[openSource - 1].text}</p>
        </blockquote>
      )}

      {state.result && (
        <p className="text-2xs text-chart-2">
          {sources.length} source{sources.length === 1 ? '' : 's'} · {state.result.highlight_ids.length} entities lit on the graph
          · {(state.result.latency_ms / 1000).toFixed(1)}s
        </p>
      )}
    </div>
  )
}

function describeInput(step: AgentStep): string {
  const i = step.input as Record<string, unknown>
  if (step.tool === 'run_cypher') return String(i.purpose ?? '')
  if (step.tool === 'explore_entities') return `${(i.entity_ids as string[] | undefined)?.length ?? 0} entities, depth ${i.depth ?? 1}`
  return String(i.query ?? '')
}

function StepRow({ step }: { step: AgentStep }) {
  const meta = TOOL_META[step.tool] ?? { label: step.tool, icon: Search }
  const Icon = meta.icon
  const pending = step.summary === undefined
  const [open, setOpen] = useState(false)
  return (
    <li className="text-xs">
      <button className="flex items-start gap-2 w-full text-left" onClick={() => setOpen(o => !o)}>
        <span className="mt-0.5 shrink-0 text-chart-3"><Icon size={12} /></span>
        <span className="flex-1 min-w-0">
          <span className="font-medium text-foreground">{meta.label}</span>
          <span className="text-chart-2"> · {describeInput(step)}</span>
          {!pending && (
            <span className={`block ${step.is_error ? 'text-foreground' : 'text-chart-2'}`}>{step.summary}</span>
          )}
        </span>
        <span className="mt-0.5 shrink-0">
          {pending ? <Loader2 size={11} className="animate-spin text-chart-2" />
            : step.is_error ? <AlertTriangle size={11} className="text-chart-4" />
            : <Check size={11} className="text-chart-3" />}
        </span>
      </button>
      {open && step.tool === 'run_cypher' && (
        <pre className="mt-1 ml-5 border border-border rounded-sm p-2 text-2xs font-mono text-chart-3 whitespace-pre-wrap bg-secondary">
          {String((step.input as { cypher?: string }).cypher ?? '')}
        </pre>
      )}
    </li>
  )
}
