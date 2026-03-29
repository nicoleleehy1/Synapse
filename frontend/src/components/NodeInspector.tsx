import { Plus, Trash2, X } from 'lucide-react'
import type { FGNode, FGLink } from '../types/graph'

interface Props {
  node: FGNode
  links: FGLink[]
  nodeMap: Map<string, FGNode>
  onClose: () => void
  onExpand: (node: FGNode) => void
  onAddEdge: (sourceNode: FGNode) => void
  onDeleteNode: (node: FGNode) => void
  onDeleteEdge: (edge: FGLink) => void
}

const TYPE_BG: Record<string, string> = {
  PERSON: '#1a1a1a', ORGANIZATION: '#404040', LOCATION: '#404040',
  TECHNOLOGY: '#525252', EVENT: '#525252', CONCEPT: '#a3a3a3',
  PRODUCT: '#a3a3a3', OTHER: '#d4d4d4',
}

export function NodeInspector({
  node, links, nodeMap, onClose,
  onExpand, onAddEdge, onDeleteNode, onDeleteEdge,
}: Props) {
  const outgoing = links.filter(
    (l) => (typeof l.source === 'object' ? l.source.id : l.source) === node.id,
  )
  const incoming = links.filter(
    (l) => (typeof l.target === 'object' ? l.target.id : l.target) === node.id,
  )
  const typeBg = TYPE_BG[node.type] ?? TYPE_BG.OTHER

  return (
    <div className="absolute right-0 top-0 h-full w-72 bg-background border-l border-border flex flex-col z-10">

      {/* Header */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0 pr-3">
            <span
              className="inline-block text-2xs font-medium px-1.5 py-0.5 rounded-sm mb-2"
              style={{ backgroundColor: typeBg, color: node.textColor ?? '#ffffff' }}
            >
              {node.type}
            </span>
            <h3 className="text-base font-semibold text-foreground leading-tight break-words">
              {node.name}
            </h3>
          </div>
          <button onClick={onClose} className="text-chart-2 hover:text-foreground transition-colors mt-0.5 shrink-0">
            <X size={15} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        {node.description && (
          <p className="text-sm text-chart-3 leading-relaxed">{node.description}</p>
        )}

        <div className="text-xs text-chart-2 space-y-1">
          <div className="truncate">{node.source_document}</div>
          <div>
            {outgoing.length + incoming.length} connections
            {node.chunk_count > 0 && ` · ${node.chunk_count} source chunks`}
          </div>
        </div>

        {outgoing.length > 0 && (
          <RelSection
            title="Outgoing"
            rels={outgoing}
            nodeMap={nodeMap}
            direction="out"
            onDeleteEdge={onDeleteEdge}
          />
        )}
        {incoming.length > 0 && (
          <RelSection
            title="Incoming"
            rels={incoming}
            nodeMap={nodeMap}
            direction="in"
            onDeleteEdge={onDeleteEdge}
          />
        )}
      </div>

      {/* Footer actions */}
      <div className="px-5 py-4 border-t border-border space-y-2">
        <button
          onClick={() => onExpand(node)}
          className="w-full py-2 border border-foreground text-foreground text-sm font-medium rounded hover:bg-foreground hover:text-background transition-colors"
        >
          Expand neighbourhood
        </button>
        <button
          onClick={() => onAddEdge(node)}
          className="w-full py-2 border border-border text-chart-3 text-sm rounded hover:border-chart-3 hover:text-foreground transition-colors flex items-center justify-center gap-1.5"
        >
          <Plus size={13} />
          Add relationship
        </button>
        <button
          onClick={() => onDeleteNode(node)}
          className="w-full py-2 text-chart-2 text-sm rounded hover:text-foreground transition-colors flex items-center justify-center gap-1.5"
        >
          <Trash2 size={13} />
          Delete entity
        </button>
      </div>
    </div>
  )
}

function RelSection({
  title, rels, nodeMap, direction, onDeleteEdge,
}: {
  title: string
  rels: FGLink[]
  nodeMap: Map<string, FGNode>
  direction: 'in' | 'out'
  onDeleteEdge: (edge: FGLink) => void
}) {
  return (
    <div>
      <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest mb-2">{title}</p>
      <ul className="space-y-2">
        {rels.map((l) => {
          const otherId =
            direction === 'out'
              ? typeof l.target === 'object' ? l.target.id : l.target
              : typeof l.source === 'object' ? l.source.id : l.source
          const other = nodeMap.get(otherId)
          return (
            <li key={l.id} className="border border-border rounded p-2.5 space-y-1 group relative">
              <div className="flex items-center justify-between gap-2">
                <span className="text-2xs font-mono font-medium text-foreground truncate">
                  {l.type}
                </span>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-2xs text-chart-2">{(l.confidence * 100).toFixed(0)}%</span>
                  <button
                    onClick={() => onDeleteEdge(l)}
                    className="opacity-0 group-hover:opacity-100 text-chart-2 hover:text-foreground transition-all"
                    title="Delete relationship"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
              <div className="text-xs text-chart-3 truncate">
                {direction === 'out' ? '→ ' : '← '}{other?.name ?? otherId}
              </div>
              {l.description && (
                <div className="text-2xs text-chart-2 line-clamp-2">{l.description}</div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
