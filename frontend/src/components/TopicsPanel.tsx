import { useEffect, useState } from 'react'
import { ChevronRight, Layers } from 'lucide-react'
import { listTopics } from '../api/client'
import type { Topic } from '../types/graph'

interface Props {
  /** Bumped by the parent whenever the graph changes, to refetch. */
  refreshKey: number
  activeId: string | null
  onSelect: (topic: Topic | null) => void
}

/** Two-level topic hierarchy from community detection; clicking one lights it up on the graph. */
export function TopicsPanel({ refreshKey, activeId, onSelect }: Props) {
  const [topics, setTopics] = useState<Topic[]>([])
  const [open, setOpen] = useState<Set<string>>(new Set())

  useEffect(() => {
    let cancelled = false
    // Topic reports are built in the background after an upload, so check again shortly after.
    const load = () => listTopics().then(t => { if (!cancelled) setTopics(t) }).catch(() => {})
    load()
    const timer = setTimeout(load, 15000)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [refreshKey])

  const top = topics.filter(t => t.level === 1)
  if (top.length === 0) return null

  const toggle = (id: string) => setOpen(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const row = (t: Topic, child = false) => (
    <button
      key={t.id}
      onClick={() => onSelect(activeId === t.id ? null : t)}
      className={`w-full text-left rounded-sm px-2 py-1.5 transition-colors ${child ? 'pl-6' : ''} ${
        activeId === t.id ? 'bg-foreground text-background' : 'hover:bg-secondary'
      }`}
      title={t.summary}
    >
      <span className="text-xs font-medium">{t.title}</span>
      <span className={`ml-1 text-2xs ${activeId === t.id ? 'text-chart-1' : 'text-chart-2'}`}>{t.size}</span>
    </button>
  )

  return (
    <section className="px-7 py-6 border-b border-border">
      <p className="flex items-center gap-1.5 text-2xs font-semibold text-chart-2 uppercase tracking-widest mb-3">
        <Layers size={11} /> Topics
      </p>
      <div className="space-y-0.5">
        {top.map(t => {
          const children = topics.filter(c => c.parent_id === t.id)
          return (
            <div key={t.id}>
              <div className="flex items-center">
                {children.length > 0 ? (
                  <button onClick={() => toggle(t.id)} className="p-0.5 text-chart-2 hover:text-foreground" aria-label="Expand">
                    <ChevronRight size={12} className={`transition-transform ${open.has(t.id) ? 'rotate-90' : ''}`} />
                  </button>
                ) : <span className="w-4" />}
                <div className="flex-1 min-w-0">{row(t)}</div>
              </div>
              {open.has(t.id) && children.map(c => row(c, true))}
            </div>
          )
        })}
      </div>
      {activeId && (
        <p className="mt-3 text-xs text-chart-3 leading-relaxed">
          {topics.find(t => t.id === activeId)?.summary}
        </p>
      )}
    </section>
  )
}
