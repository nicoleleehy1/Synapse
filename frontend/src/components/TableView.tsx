import { useState, useMemo } from 'react'
import { Search, ChevronUp, ChevronDown, Trash2, Plus } from 'lucide-react'
import type { FGData, FGNode } from '../types/graph'

const ENTITY_TYPES = ['PERSON', 'ORGANIZATION', 'TECHNOLOGY', 'EVENT', 'LOCATION', 'CONCEPT', 'PRODUCT', 'OTHER'] as const

const TYPE_BADGE: Record<string, { bg: string; text: string }> = {
  PERSON:       { bg: '#1a1a1a', text: '#ffffff' },
  ORGANIZATION: { bg: '#404040', text: '#ffffff' },
  TECHNOLOGY:   { bg: '#525252', text: '#ffffff' },
  EVENT:        { bg: '#525252', text: '#ffffff' },
  LOCATION:     { bg: '#404040', text: '#ffffff' },
  CONCEPT:      { bg: '#a3a3a3', text: '#0a0a0a' },
  PRODUCT:      { bg: '#a3a3a3', text: '#0a0a0a' },
  OTHER:        { bg: '#d4d4d4', text: '#0a0a0a' },
}

type SortKey = 'name' | 'type' | 'connections'
type EditField = 'name' | 'type' | 'description'
type EditingCell = { nodeId: string; field: EditField; value: string }

interface Props {
  graph: FGData
  selectedNodeId: string | null
  onNodeSelect: (node: FGNode | null) => void
  onEditNode: (nodeId: string, updates: { name?: string; type?: string; description?: string }) => void
  onDeleteNode: (nodeId: string) => void
  onCreateNode: (name: string, type: string) => void
}

export function TableView({ graph, selectedNodeId, onNodeSelect, onEditNode, onDeleteNode, onCreateNode }: Props) {
  const [search, setSearch] = useState('')
  const [filterTypes, setFilterTypes] = useState<Set<string>>(new Set())
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [editing, setEditing] = useState<EditingCell | null>(null)

  // Connection count per node
  const connCount = useMemo(() => {
    const counts = new Map<string, number>()
    for (const n of graph.nodes) counts.set(n.id, 0)
    for (const l of graph.links) {
      const s = typeof l.source === 'object' ? (l.source as FGNode).id : l.source as string
      const t = typeof l.target === 'object' ? (l.target as FGNode).id : l.target as string
      counts.set(s, (counts.get(s) ?? 0) + 1)
      counts.set(t, (counts.get(t) ?? 0) + 1)
    }
    return counts
  }, [graph])

  // Connected node names per node (for tooltip)
  const connNames = useMemo(() => {
    const names = new Map<string, string[]>()
    const nodeById = new Map(graph.nodes.map(n => [n.id, n.name]))
    for (const n of graph.nodes) names.set(n.id, [])
    for (const l of graph.links) {
      const s = typeof l.source === 'object' ? (l.source as FGNode).id : l.source as string
      const t = typeof l.target === 'object' ? (l.target as FGNode).id : l.target as string
      names.get(s)?.push(nodeById.get(t) ?? t)
      names.get(t)?.push(nodeById.get(s) ?? s)
    }
    return names
  }, [graph])

  // Filtered + sorted rows
  const rows = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = graph.nodes.filter(n => {
      if (filterTypes.size > 0 && !filterTypes.has(n.type)) return false
      if (q) return n.name.toLowerCase().includes(q) || (n.description ?? '').toLowerCase().includes(q)
      return true
    })
    return [...filtered].sort((a, b) => {
      const cmp =
        sortKey === 'name' ? a.name.localeCompare(b.name)
        : sortKey === 'type' ? a.type.localeCompare(b.type)
        : (connCount.get(a.id) ?? 0) - (connCount.get(b.id) ?? 0)
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [graph.nodes, search, filterTypes, sortKey, sortDir, connCount])

  const presentTypes = useMemo(() => [...new Set(graph.nodes.map(n => n.type))].sort(), [graph.nodes])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const toggleType = (type: string) => {
    setFilterTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const startEdit = (node: FGNode, field: EditField, e: React.MouseEvent) => {
    e.stopPropagation()
    const value = field === 'name' ? node.name : field === 'type' ? node.type : (node.description ?? '')
    setEditing({ nodeId: node.id, field, value })
  }

  const commitEdit = (nodeId: string, field: EditField, value: string) => {
    const trimmed = value.trim()
    if (trimmed) onEditNode(nodeId, { [field]: trimmed })
    setEditing(null)
  }

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return <ChevronUp size={11} className="opacity-20" />
    return sortDir === 'asc' ? <ChevronUp size={11} /> : <ChevronDown size={11} />
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── Toolbar ───────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0 flex-wrap gap-y-2">
        {/* Search */}
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-chart-2 pointer-events-none" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter…"
            className="pl-8 pr-3 py-1.5 text-xs bg-transparent border border-border rounded-sm text-foreground placeholder:text-chart-2 focus:outline-hidden focus:border-chart-3 w-44"
          />
        </div>

        {/* Type filter pills */}
        <div className="flex gap-1.5 flex-wrap">
          {presentTypes.map(type => {
            const s = TYPE_BADGE[type] ?? TYPE_BADGE.OTHER
            const active = filterTypes.has(type)
            return (
              <button
                key={type}
                onClick={() => toggleType(type)}
                className="text-2xs px-2 py-0.5 rounded-sm transition-all"
                style={{
                  background: active ? s.bg : 'transparent',
                  color: active ? s.text : '#a3a3a3',
                  border: `1px solid ${active ? s.bg : '#e2e2e2'}`,
                  opacity: filterTypes.size > 0 && !active ? 0.45 : 1,
                }}
              >
                {type}
              </button>
            )
          })}
        </div>

        <span className="text-2xs text-chart-2 ml-auto shrink-0">
          {rows.length} {rows.length === 1 ? 'entity' : 'entities'}
        </span>
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 bg-background z-10">
            <tr className="border-b border-border">
              <th
                className="text-left px-5 py-2.5 font-medium text-chart-2 cursor-pointer select-none hover:text-foreground transition-colors w-[26%]"
                onClick={() => toggleSort('name')}
              >
                <span className="flex items-center gap-1">Name <SortIcon col="name" /></span>
              </th>
              <th
                className="text-left px-4 py-2.5 font-medium text-chart-2 cursor-pointer select-none hover:text-foreground transition-colors w-[130px]"
                onClick={() => toggleSort('type')}
              >
                <span className="flex items-center gap-1">Type <SortIcon col="type" /></span>
              </th>
              <th className="text-left px-4 py-2.5 font-medium text-chart-2">
                Description
              </th>
              <th
                className="text-right px-4 py-2.5 font-medium text-chart-2 cursor-pointer select-none hover:text-foreground transition-colors w-[70px]"
                onClick={() => toggleSort('connections')}
              >
                <span className="flex items-center justify-end gap-1">Links <SortIcon col="connections" /></span>
              </th>
              <th className="w-[40px]" />
            </tr>
          </thead>

          <tbody>
            {rows.map(node => {
              const isSelected = node.id === selectedNodeId
              const count = connCount.get(node.id) ?? 0
              const badge = TYPE_BADGE[node.type] ?? TYPE_BADGE.OTHER
              const ed = editing?.nodeId === node.id ? editing : null

              return (
                <tr
                  key={node.id}
                  onClick={() => onNodeSelect(isSelected ? null : node)}
                  className={`group border-b border-border transition-colors cursor-pointer ${
                    isSelected ? 'bg-accent' : 'hover:bg-secondary'
                  }`}
                >
                  {/* Name */}
                  <td
                    className="px-5 py-2 font-medium text-foreground"
                    onClick={e => startEdit(node, 'name', e)}
                  >
                    {ed?.field === 'name' ? (
                      <input
                        autoFocus
                        value={ed.value}
                        onChange={e => setEditing({ ...ed, value: e.target.value })}
                        onBlur={() => commitEdit(node.id, 'name', ed.value)}
                        onKeyDown={e => {
                          e.stopPropagation()
                          if (e.key === 'Enter') commitEdit(node.id, 'name', ed.value)
                          if (e.key === 'Escape') setEditing(null)
                        }}
                        onClick={e => e.stopPropagation()}
                        className="w-full bg-transparent border-b border-chart-3 outline-hidden text-foreground"
                      />
                    ) : (
                      <span className="block truncate">{node.name}</span>
                    )}
                  </td>

                  {/* Type */}
                  <td
                    className="px-4 py-2"
                    onClick={e => startEdit(node, 'type', e)}
                  >
                    {ed?.field === 'type' ? (
                      <select
                        autoFocus
                        value={ed.value}
                        onChange={e => {
                          const v = e.target.value
                          onEditNode(node.id, { type: v })
                          setEditing(null)
                        }}
                        onBlur={() => setEditing(null)}
                        onKeyDown={e => { if (e.key === 'Escape') setEditing(null) }}
                        onClick={e => e.stopPropagation()}
                        className="bg-background border border-border rounded-sm text-xs text-foreground outline-hidden py-0.5 px-1"
                      >
                        {ENTITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    ) : (
                      <span
                        className="inline-block px-1.5 py-0.5 rounded-sm text-2xs font-medium"
                        style={{ background: badge.bg, color: badge.text }}
                      >
                        {node.type}
                      </span>
                    )}
                  </td>

                  {/* Description */}
                  <td
                    className="px-4 py-2 text-chart-3 max-w-0"
                    onClick={e => startEdit(node, 'description', e)}
                  >
                    {ed?.field === 'description' ? (
                      <textarea
                        autoFocus
                        value={ed.value}
                        onChange={e => setEditing({ ...ed, value: e.target.value })}
                        onBlur={() => commitEdit(node.id, 'description', ed.value)}
                        onKeyDown={e => {
                          e.stopPropagation()
                          if (e.key === 'Escape') setEditing(null)
                        }}
                        onClick={e => e.stopPropagation()}
                        rows={2}
                        className="w-full bg-transparent border-b border-chart-3 outline-hidden text-foreground resize-none"
                      />
                    ) : node.description ? (
                      <span className="block truncate">{node.description}</span>
                    ) : (
                      <span className="opacity-30 italic">—</span>
                    )}
                  </td>

                  {/* Connections */}
                  <td className="px-4 py-2 text-right tabular-nums text-chart-3">
                    {count > 0 ? (
                      <span
                        title={(connNames.get(node.id) ?? []).join(', ')}
                        className="cursor-help"
                      >
                        {count}
                      </span>
                    ) : (
                      <span className="opacity-30">—</span>
                    )}
                  </td>

                  {/* Delete */}
                  <td className="px-2 py-2" onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => { onDeleteNode(node.id); if (isSelected) onNodeSelect(null) }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-chart-2 hover:text-foreground p-1 rounded-sm"
                      title="Delete entity"
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {rows.length === 0 && (
          <div className="flex items-center justify-center py-16 text-xs text-chart-2">
            {search || filterTypes.size > 0 ? 'No matching entities' : 'No entities yet'}
          </div>
        )}
      </div>

      {/* ── Footer ────────────────────────────────────────────────────────────── */}
      <div className="border-t border-border px-5 py-2.5 shrink-0">
        <button
          onClick={() => onCreateNode('New Entity', 'CONCEPT')}
          className="flex items-center gap-1.5 text-xs text-chart-2 hover:text-foreground transition-colors"
        >
          <Plus size={12} />
          New entity
        </button>
      </div>
    </div>
  )
}
