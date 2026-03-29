import { useRef, useState } from 'react'
import { X } from 'lucide-react'
import type { FGNode, CreateNodePayload } from '../types/graph'

const ENTITY_TYPES = ['PERSON','ORGANIZATION','LOCATION','CONCEPT','EVENT','TECHNOLOGY','PRODUCT','OTHER']

interface Props {
  parentNode: FGNode
  onConfirm: (payload: CreateNodePayload) => void
  onClose: () => void
}

export function AddNodeModal({ parentNode, onConfirm, onClose }: Props) {
  const [name, setName] = useState('')
  const [type, setType] = useState('CONCEPT')
  const [description, setDescription] = useState('')
  const [relType, setRelType] = useState('')
  const [direction, setDirection] = useState<'out' | 'in'>('out')
  const [confidence, setConfidence] = useState(1.0)
  const [error, setError] = useState('')
  const nameRef = useRef<HTMLInputElement>(null)

  const submit = () => {
    if (!name.trim()) { setError('Name is required.'); nameRef.current?.focus(); return }
    if (!relType.trim()) { setError('Relationship type is required.'); return }
    setError('')
    onConfirm({
      name: name.trim(),
      type,
      description: description.trim() || undefined,
      parent_entity_id: parentNode.id,
      relationship_type: relType.trim().toUpperCase().replace(/\s+/g, '_'),
      relationship_direction: direction,
      confidence,
    })
  }

  return (
    <Backdrop onClose={onClose}>
      <div className="w-full max-w-md bg-background border border-border rounded p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-foreground">Add connected node</h2>
            <p className="text-xs text-chart-2 mt-0.5">
              Connected to <span className="text-foreground font-medium">{parentNode.name}</span>
            </p>
          </div>
          <button onClick={onClose} className="text-chart-2 hover:text-foreground transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Fields */}
        <div className="space-y-4">
          <Field label="Name *">
            <input
              ref={nameRef}
              autoFocus
              className={input}
              placeholder="e.g. OpenAI"
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submit()}
            />
          </Field>

          <Field label="Type">
            <select className={input} value={type} onChange={e => setType(e.target.value)}>
              {ENTITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>

          <Field label="Description">
            <input
              className={input}
              placeholder="Optional short description"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Relationship type *">
              <input
                className={input}
                placeholder="e.g. FOUNDED_BY"
                value={relType}
                onChange={e => setRelType(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submit()}
              />
            </Field>
            <Field label="Direction">
              <select className={input} value={direction} onChange={e => setDirection(e.target.value as 'out' | 'in')}>
                <option value="out">Parent → New</option>
                <option value="in">New → Parent</option>
              </select>
            </Field>
          </div>

          <Field label={`Confidence — ${Math.round(confidence * 100)}%`}>
            <input
              type="range" min={0} max={1} step={0.05}
              value={confidence}
              onChange={e => setConfidence(parseFloat(e.target.value))}
              className="w-full accent-foreground"
            />
          </Field>
        </div>

        {error && <p className="text-xs text-foreground bg-secondary border border-border rounded px-3 py-2">{error}</p>}

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} className={btnPrimary}>Add node</button>
        </div>
      </div>
    </Backdrop>
  )
}

// ── Add Edge Modal ─────────────────────────────────────────────────────────

interface AddEdgeProps {
  sourceNode: FGNode
  allNodes: FGNode[]
  onConfirm: (payload: import('../types/graph').CreateEdgePayload) => void
  onClose: () => void
}

export function AddEdgeModal({ sourceNode, allNodes, onConfirm, onClose }: AddEdgeProps) {
  const [targetSearch, setTargetSearch] = useState('')
  const [targetId, setTargetId] = useState('')
  const [relType, setRelType] = useState('')
  const [description, setDescription] = useState('')
  const [confidence, setConfidence] = useState(1.0)
  const [error, setError] = useState('')

  const candidates = allNodes
    .filter(n => n.id !== sourceNode.id && n.name.toLowerCase().includes(targetSearch.toLowerCase()))
    .slice(0, 8)

  const selectedTarget = allNodes.find(n => n.id === targetId)

  const submit = () => {
    if (!targetId) { setError('Select a target node.'); return }
    if (!relType.trim()) { setError('Relationship type is required.'); return }
    setError('')
    onConfirm({
      source_entity_id: sourceNode.id,
      target_entity_id: targetId,
      type: relType.trim().toUpperCase().replace(/\s+/g, '_'),
      description: description.trim() || undefined,
      confidence,
    })
  }

  return (
    <Backdrop onClose={onClose}>
      <div className="w-full max-w-md bg-background border border-border rounded p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-foreground">Add relationship</h2>
            <p className="text-xs text-chart-2 mt-0.5">
              From <span className="text-foreground font-medium">{sourceNode.name}</span>
            </p>
          </div>
          <button onClick={onClose} className="text-chart-2 hover:text-foreground transition-colors"><X size={16} /></button>
        </div>

        <div className="space-y-4">
          {/* Target search */}
          <Field label="Target node *">
            {selectedTarget ? (
              <div className="flex items-center justify-between border border-border rounded px-3 py-2">
                <span className="text-sm text-foreground">{selectedTarget.name}</span>
                <button onClick={() => { setTargetId(''); setTargetSearch('') }} className="text-chart-2 hover:text-foreground">
                  <X size={12} />
                </button>
              </div>
            ) : (
              <div className="relative">
                <input
                  autoFocus
                  className={input}
                  placeholder="Search nodes…"
                  value={targetSearch}
                  onChange={e => setTargetSearch(e.target.value)}
                />
                {targetSearch && candidates.length > 0 && (
                  <ul className="absolute z-10 top-full mt-1 w-full bg-background border border-border rounded overflow-hidden text-sm">
                    {candidates.map(n => (
                      <li
                        key={n.id}
                        onClick={() => { setTargetId(n.id); setTargetSearch(n.name) }}
                        className="px-3 py-2 hover:bg-secondary cursor-pointer flex items-center gap-2"
                      >
                        <span className="text-2xs text-chart-2 uppercase tracking-wide">{n.type}</span>
                        <span className="text-foreground">{n.name}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Field>

          <Field label="Relationship type *">
            <input
              className={input}
              placeholder="e.g. COLLABORATED_WITH"
              value={relType}
              onChange={e => setRelType(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submit()}
            />
          </Field>

          <Field label="Description">
            <input
              className={input}
              placeholder="Optional"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </Field>

          <Field label={`Confidence — ${Math.round(confidence * 100)}%`}>
            <input
              type="range" min={0} max={1} step={0.05}
              value={confidence}
              onChange={e => setConfidence(parseFloat(e.target.value))}
              className="w-full accent-foreground"
            />
          </Field>
        </div>

        {error && <p className="text-xs text-foreground bg-secondary border border-border rounded px-3 py-2">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={submit} className={btnPrimary}>Add relationship</button>
        </div>
      </div>
    </Backdrop>
  )
}

// ── Shared primitives ──────────────────────────────────────────────────────

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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-2xs font-semibold text-chart-2 uppercase tracking-widest">{label}</label>
      {children}
    </div>
  )
}

const input = 'w-full border border-border rounded px-3 py-2 text-sm text-foreground bg-background placeholder-chart-2 focus:outline-none focus:border-chart-3 transition-colors'
const btnPrimary = 'px-4 py-2 bg-foreground text-background text-sm font-medium rounded hover:bg-chart-4 transition-colors'
const btnSecondary = 'px-4 py-2 border border-border text-chart-3 text-sm rounded hover:border-chart-3 hover:text-foreground transition-colors'
