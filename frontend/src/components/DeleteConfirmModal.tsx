import { X } from 'lucide-react'
import type { GraphNode } from '../types/graph'

// ── Delete Node Modal ──────────────────────────────────────────────────────

interface DeleteNodeProps {
  nodeName: string
  orphans: GraphNode[]          // nodes that would be isolated
  onDeleteOnly: () => void      // delete node, keep neighbours
  onDeleteCascade: () => void   // delete node + orphaned neighbours
  onClose: () => void
}

export function DeleteNodeModal({ nodeName, orphans, onDeleteOnly, onDeleteCascade, onClose }: DeleteNodeProps) {
  const hasOrphans = orphans.length > 0

  return (
    <Backdrop onClose={onClose}>
      <div className="w-full max-w-sm bg-background border border-border rounded p-6 space-y-5">
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-foreground">Delete entity</h2>
          <button onClick={onClose} className="text-chart-2 hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>

        <p className="text-sm text-chart-3 leading-relaxed">
          You are about to delete{' '}
          <span className="font-semibold text-foreground">{nodeName}</span>.
        </p>

        {hasOrphans && (
          <div className="border border-border rounded p-3 space-y-2">
            <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest">
              {orphans.length} node{orphans.length > 1 ? 's' : ''} would become isolated
            </p>
            <ul className="space-y-1">
              {orphans.slice(0, 6).map(n => (
                <li key={n.id} className="text-xs text-chart-3 flex items-center gap-2">
                  <span className="text-2xs text-chart-2 uppercase">{n.type}</span>
                  <span>{n.name}</span>
                </li>
              ))}
              {orphans.length > 6 && (
                <li className="text-xs text-chart-2">+{orphans.length - 6} more</li>
              )}
            </ul>
          </div>
        )}

        <div className="flex flex-col gap-2 pt-1">
          {hasOrphans && (
            <button
              onClick={onDeleteCascade}
              className="w-full py-2 bg-foreground text-background text-sm font-medium rounded hover:bg-chart-4 transition-colors"
            >
              Delete {nodeName} + {orphans.length} isolated node{orphans.length > 1 ? 's' : ''}
            </button>
          )}
          <button
            onClick={onDeleteOnly}
            className={`w-full py-2 text-sm font-medium rounded transition-colors ${
              hasOrphans
                ? 'border border-border text-chart-3 hover:border-chart-3 hover:text-foreground'
                : 'bg-foreground text-background hover:bg-chart-4'
            }`}
          >
            {hasOrphans ? `Delete only ${nodeName}` : `Delete ${nodeName}`}
          </button>
          <button
            onClick={onClose}
            className="w-full py-2 text-sm text-chart-2 hover:text-foreground transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </Backdrop>
  )
}

// ── Delete Edge Modal ──────────────────────────────────────────────────────

interface DeleteEdgeProps {
  relType: string
  sourceName: string
  targetName: string
  orphanTarget: GraphNode | null   // target node would be isolated if edge deleted
  onDeleteOnly: () => void
  onDeleteCascade: () => void      // delete edge + orphaned target
  onClose: () => void
}

export function DeleteEdgeModal({
  relType, sourceName, targetName, orphanTarget,
  onDeleteOnly, onDeleteCascade, onClose,
}: DeleteEdgeProps) {
  return (
    <Backdrop onClose={onClose}>
      <div className="w-full max-w-sm bg-background border border-border rounded p-6 space-y-5">
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-foreground">Delete relationship</h2>
          <button onClick={onClose} className="text-chart-2 hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="border border-border rounded p-3 space-y-1 text-sm">
          <p className="text-foreground font-medium">{sourceName}</p>
          <p className="text-2xs font-mono text-chart-2">↓ {relType}</p>
          <p className="text-foreground font-medium">{targetName}</p>
        </div>

        {orphanTarget && (
          <p className="text-sm text-chart-3 leading-relaxed">
            <span className="font-semibold text-foreground">{orphanTarget.name}</span> has no other
            connections — it would become isolated.
          </p>
        )}

        <div className="flex flex-col gap-2 pt-1">
          {orphanTarget && (
            <button
              onClick={onDeleteCascade}
              className="w-full py-2 bg-foreground text-background text-sm font-medium rounded hover:bg-chart-4 transition-colors"
            >
              Delete relationship + {orphanTarget.name}
            </button>
          )}
          <button
            onClick={onDeleteOnly}
            className={`w-full py-2 text-sm font-medium rounded transition-colors ${
              orphanTarget
                ? 'border border-border text-chart-3 hover:border-chart-3 hover:text-foreground'
                : 'bg-foreground text-background hover:bg-chart-4'
            }`}
          >
            Delete relationship only
          </button>
          <button
            onClick={onClose}
            className="w-full py-2 text-sm text-chart-2 hover:text-foreground transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </Backdrop>
  )
}

// ── Shared ─────────────────────────────────────────────────────────────────

function Backdrop({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 backdrop-blur-sm px-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {children}
    </div>
  )
}
