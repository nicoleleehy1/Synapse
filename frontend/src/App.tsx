import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { FileUpload } from './components/FileUpload'
import { GraphCanvas } from './components/GraphCanvas'
import { NodeInspector } from './components/NodeInspector'
import { QueryPanel } from './components/QueryPanel'
import { Legend } from './components/Legend'
import { AddNodeModal, AddEdgeModal } from './components/AddNodeModal'
import { DeleteNodeModal, DeleteEdgeModal } from './components/DeleteConfirmModal'
import { useDocumentUpload } from './hooks/useDocumentUpload'
import { useGraphData } from './hooks/useGraphData'
import {
  deleteDocument, createNode, createEdge,
  deleteNode, deleteEdge,
  getNodeOrphans, getEdgeOrphanTarget,
} from './api/client'
import type { DocumentStatus, FGNode, FGLink, GraphNode } from './types/graph'
import { SAMPLE_GRAPH } from './data/sampleGraph'

// ── Modal state types ──────────────────────────────────────────────────────

type AddNodeState  = { parentNode: FGNode }
type AddEdgeState  = { sourceNode: FGNode }
type DelNodeState  = { node: FGNode; orphans: GraphNode[] }
type DelEdgeState  = { edge: FGLink; orphanTarget: GraphNode | null; sourceName: string; targetName: string }

export default function App() {
  const canvasContainerRef = useRef<HTMLDivElement>(null)
  const [canvasSize, setCanvasSize] = useState({ width: 800, height: 600 })
  const [documents, setDocuments] = useState<DocumentStatus[]>([])

  // Modal state — only one open at a time
  const [addNodeModal,  setAddNodeModal]  = useState<AddNodeState | null>(null)
  const [addEdgeModal,  setAddEdgeModal]  = useState<AddEdgeState | null>(null)
  const [delNodeModal,  setDelNodeModal]  = useState<DelNodeState | null>(null)
  const [delEdgeModal,  setDelEdgeModal]  = useState<DelEdgeState | null>(null)

  const { upload, uploading, status, error } = useDocumentUpload()
  const {
    graphData, loading: graphLoading, selectedNode, setSelectedNode,
    loadFullGraph, expandNode, overlayGraph, loadSample, resetGraph,
  } = useGraphData()

  // Canvas resize
  useEffect(() => {
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setCanvasSize({ width, height })
    })
    if (canvasContainerRef.current) obs.observe(canvasContainerRef.current)
    return () => obs.disconnect()
  }, [])

  // Document lifecycle
  useEffect(() => {
    if (!status) return
    if (status.status === 'complete' || status.status === 'error') {
      setDocuments((prev) => [...prev.filter(d => d.document_id !== status.document_id), status])
      if (status.status === 'complete') loadFullGraph()
    }
  }, [status?.status, status?.document_id, loadFullGraph])

  // ── Document delete ──────────────────────────────────────────────────
  const handleDeleteDocument = async (doc: DocumentStatus) => {
    try { await deleteDocument(doc.document_id) } catch { /* ignore */ }
    setDocuments(prev => prev.filter(d => d.document_id !== doc.document_id))
    loadFullGraph()
  }

  // ── Add node (from hover button) ─────────────────────────────────────
  const handleAddNodeRequest = (parentNode: FGNode) => {
    setAddNodeModal({ parentNode })
  }
  const handleAddNodeConfirm = async (payload: Parameters<typeof createNode>[0]) => {
    const subgraph = await createNode(payload)
    overlayGraph(subgraph)
    setAddNodeModal(null)
  }

  // ── Add edge (from NodeInspector) ────────────────────────────────────
  const handleAddEdgeRequest = (sourceNode: FGNode) => {
    setAddEdgeModal({ sourceNode })
  }
  const handleAddEdgeConfirm = async (payload: Parameters<typeof createEdge>[0]) => {
    await createEdge(payload)
    await loadFullGraph()
    setAddEdgeModal(null)
  }

  // ── Delete node (from NodeInspector) ─────────────────────────────────
  const handleDeleteNodeRequest = async (node: FGNode) => {
    const { orphaned_nodes } = await getNodeOrphans(node.id)
    setDelNodeModal({ node, orphans: orphaned_nodes })
  }
  const handleDeleteNodeOnly = async () => {
    if (!delNodeModal) return
    await deleteNode(delNodeModal.node.id, false)
    setDelNodeModal(null)
    setSelectedNode(null)
    loadFullGraph()
  }
  const handleDeleteNodeCascade = async () => {
    if (!delNodeModal) return
    await deleteNode(delNodeModal.node.id, true)
    setDelNodeModal(null)
    setSelectedNode(null)
    loadFullGraph()
  }

  // ── Delete edge (from NodeInspector relationship list) ───────────────
  const handleDeleteEdgeRequest = async (edge: FGLink) => {
    const { orphaned_target } = await getEdgeOrphanTarget(edge.id)
    const nodeMap = new Map(graphData.nodes.map(n => [n.id, n]))
    const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source
    const tgtId = typeof edge.target === 'object' ? edge.target.id : edge.target
    setDelEdgeModal({
      edge,
      orphanTarget: orphaned_target,
      sourceName: nodeMap.get(srcId)?.name ?? srcId,
      targetName: nodeMap.get(tgtId)?.name ?? tgtId,
    })
  }
  const handleDeleteEdgeOnly = async () => {
    if (!delEdgeModal) return
    await deleteEdge(delEdgeModal.edge.id, false)
    setDelEdgeModal(null)
    loadFullGraph()
  }
  const handleDeleteEdgeCascade = async () => {
    if (!delEdgeModal) return
    await deleteEdge(delEdgeModal.edge.id, true)
    setDelEdgeModal(null)
    if (delEdgeModal.orphanTarget?.id === selectedNode?.id) setSelectedNode(null)
    loadFullGraph()
  }

  const nodeMap = new Map<string, FGNode>(graphData.nodes.map(n => [n.id, n]))
  const completedDocs = documents.filter(d => d.status === 'complete')

  return (
    <div className="flex h-screen bg-background overflow-hidden">

      {/* ── Sidebar ── */}
      <aside className="w-[320px] shrink-0 flex flex-col border-r border-border overflow-y-auto">
        <div className="px-7 pt-8 pb-6 border-b border-border">
          <h1 className="text-xl font-bold tracking-tight text-foreground">Knowledge Graph</h1>
          <p className="text-xs text-chart-2 mt-1">PDF → entity graph · semantic search</p>
        </div>

        <div className="flex-1 px-7 py-6 space-y-8">

          <section>
            <SectionLabel>Document</SectionLabel>
            <FileUpload onUpload={upload} uploading={uploading} status={status} error={error} />
          </section>

          {completedDocs.length > 0 && (
            <section>
              <SectionLabel>Indexed documents</SectionLabel>
              <ul className="space-y-2">
                {completedDocs.map(doc => (
                  <li key={doc.document_id} className="border border-border rounded px-3 py-2.5 flex items-start gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate" title={doc.filename}>
                        {doc.filename}
                      </p>
                      <p className="text-2xs text-chart-2 mt-0.5">
                        {doc.entity_count} entities · {doc.relationship_count} relationships
                      </p>
                    </div>
                    <button
                      onClick={() => handleDeleteDocument(doc)}
                      className="shrink-0 mt-0.5 text-chart-2 hover:text-foreground transition-colors"
                      title="Remove from graph"
                    >
                      <X size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {graphData.nodes.length > 0 && (
            <section>
              <SectionLabel>Graph</SectionLabel>
              <div className="flex items-center justify-between">
                <span className="text-xs text-chart-3">
                  {graphData.nodes.length} nodes · {graphData.links.length} edges
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => loadFullGraph()}
                    disabled={graphLoading}
                    className="text-xs text-chart-3 border border-border rounded px-3 py-1.5 hover:border-chart-3 hover:text-foreground transition-colors disabled:opacity-40"
                  >
                    {graphLoading ? 'Loading…' : 'Reload'}
                  </button>
                  <button
                    onClick={resetGraph}
                    className="text-xs text-chart-2 border border-border rounded px-3 py-1.5 hover:border-chart-3 hover:text-foreground transition-colors"
                  >
                    Clear
                  </button>
                </div>
              </div>
            </section>
          )}

          <section>
            <SectionLabel>Ask</SectionLabel>
            <QueryPanel documentId={status?.document_id} onGraphContext={overlayGraph} />
          </section>

        </div>
      </aside>

      {/* ── Canvas ── */}
      <div ref={canvasContainerRef} className="flex-1 relative bg-background">
        {graphData.nodes.length === 0 ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center select-none gap-4">
            <div className="text-center pointer-events-none">
              <p className="text-2xl font-bold text-border tracking-tight">No graph yet</p>
              <p className="text-sm text-chart-2 mt-2">Upload a PDF to extract entities and relationships</p>
            </div>
            <button
              onClick={() => loadSample(SAMPLE_GRAPH)}
              className="pointer-events-auto text-xs text-chart-3 border border-border rounded px-4 py-2 hover:border-chart-3 hover:text-foreground transition-colors"
            >
              Load sample graph
            </button>
          </div>
        ) : (
          <GraphCanvas
            data={graphData}
            selectedNodeId={selectedNode?.id ?? null}
            onNodeClick={(node) => setSelectedNode(node.id === selectedNode?.id ? null : node)}
            onAddNode={handleAddNodeRequest}
            width={canvasSize.width}
            height={canvasSize.height}
          />
        )}

        {graphData.nodes.length > 0 && <Legend />}

        {selectedNode && (
          <NodeInspector
            node={selectedNode}
            links={graphData.links}
            nodeMap={nodeMap}
            onClose={() => setSelectedNode(null)}
            onExpand={expandNode}
            onAddEdge={handleAddEdgeRequest}
            onDeleteNode={handleDeleteNodeRequest}
            onDeleteEdge={handleDeleteEdgeRequest}
          />
        )}
      </div>

      {/* ── Modals ── */}
      {addNodeModal && (
        <AddNodeModal
          parentNode={addNodeModal.parentNode}
          onConfirm={handleAddNodeConfirm}
          onClose={() => setAddNodeModal(null)}
        />
      )}
      {addEdgeModal && (
        <AddEdgeModal
          sourceNode={addEdgeModal.sourceNode}
          allNodes={graphData.nodes}
          onConfirm={handleAddEdgeConfirm}
          onClose={() => setAddEdgeModal(null)}
        />
      )}
      {delNodeModal && (
        <DeleteNodeModal
          nodeName={delNodeModal.node.name}
          orphans={delNodeModal.orphans}
          onDeleteOnly={handleDeleteNodeOnly}
          onDeleteCascade={handleDeleteNodeCascade}
          onClose={() => setDelNodeModal(null)}
        />
      )}
      {delEdgeModal && (
        <DeleteEdgeModal
          relType={delEdgeModal.edge.type}
          sourceName={delEdgeModal.sourceName}
          targetName={delEdgeModal.targetName}
          orphanTarget={delEdgeModal.orphanTarget}
          onDeleteOnly={handleDeleteEdgeOnly}
          onDeleteCascade={handleDeleteEdgeCascade}
          onClose={() => setDelEdgeModal(null)}
        />
      )}
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-2xs font-semibold text-chart-2 uppercase tracking-widest mb-3">{children}</p>
}
